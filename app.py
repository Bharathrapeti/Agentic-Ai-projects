"""Polished Streamlit AI Interview Coach."""

from __future__ import annotations

import secrets
import smtplib
import logging
import inspect
import html
import streamlit as st
from datetime import datetime, timedelta, timezone

import auth_helpers

import ai_service
import capture
import database
from live_interview import live_interview

logger = logging.getLogger(__name__)

try:
    from streamlit_webrtc import webrtc_streamer  # noqa: F401

    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False

st.set_page_config(page_title="Interview Coach", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")
database.init_db()

st.markdown("""<style>
.block-container {max-width: 1220px; padding-top: 1.5rem;}
/* Keep the workspace focused on the interview instead of deployment controls. */
.stDeployButton, [data-testid="stAppDeployButton"] {display: none !important;}
.hero {padding: 2rem 2.2rem; border-radius: 22px; background: linear-gradient(120deg,#172554,#312e81 55%,#4338ca); color:white; margin-bottom:1.2rem; box-shadow:0 14px 35px rgba(30,41,99,.18);}
.hero h1 {font-size:2.4rem; margin-bottom:.35rem;}
.hero p {font-size:1.05rem; opacity:.9; margin:0;}
.feature-card {padding:1rem 1.1rem; border:1px solid #e2e8f0; border-radius:16px; background:#fff; min-height:108px; box-shadow:0 4px 15px rgba(15,23,42,.04);}
.feature-card strong {display:block; margin-bottom:.3rem; color:#0f172a;}
.feature-card span {color:#64748b; font-size:.9rem;}
.section-card {padding:1.2rem 1.35rem; border-radius:18px; background:#f8fafc; border:1px solid #e2e8f0; margin:1rem 0;}
.muted {color:#64748b; font-size:.9rem;}
.live-shell {padding:1rem 1.1rem; border:1px solid #263449; border-radius:20px; background:linear-gradient(145deg,#0f172a,#111827); margin:.8rem 0 1.1rem;}
.live-kicker {color:#94a3b8; font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; margin-bottom:.45rem;}
.live-question-card {padding:1.15rem 1.25rem; border:1px solid #334155; border-left:4px solid #6366f1; border-radius:14px; background:#172033; color:#f8fafc; font-size:1.18rem; line-height:1.55; overflow-wrap:anywhere; box-shadow:0 8px 22px rgba(2,6,23,.18);}
.live-status {display:inline-flex; align-items:center; gap:.45rem; padding:.35rem .65rem; border:1px solid #334155; border-radius:999px; color:#cbd5e1; background:#111827; font-size:.78rem; font-weight:600;}
.live-status-dot {width:.45rem; height:.45rem; border-radius:50%; background:#22c55e; box-shadow:0 0 0 3px rgba(34,197,94,.14);}
.live-history-card {padding:.8rem 1rem; border:1px solid #263449; border-radius:12px; background:#111827; margin:.65rem 0;}
.live-history-card .stMarkdown {margin-bottom:0;}
@media (max-width: 800px) {.block-container {padding-left:1rem; padding-right:1rem;} .live-question-card {font-size:1.05rem;}}
</style>""", unsafe_allow_html=True)


def reset():
    for key in ("session_id", "questions", "current", "evaluations", "report", "submitted", "topics", "initial_count", "adaptive_mode", "live_mode", "live_transcript", "live_last_event", "live_replay", "password_reset", "setup_details", "setup_submitted", "camera_confirmed", "voice_test_passed", "voice_test_text", "voice_test_error"):
        st.session_state.pop(key, None)


def opening_question(name: str, role: str) -> str:
    return (
        f"Hi {name.strip()}, welcome to your {role} interview. "
        "To get started, please tell me about yourself, your background, "
        "and the kind of work you enjoy."
    )


def login_view():
    st.markdown(
        '<div class="hero"><h1>🎯 Welcome to Interview Coach</h1>'
        '<p>Sign in to save your practice sessions, feedback, and progress.</p></div>',
        unsafe_allow_html=True,
    )
    login_tab, register_tab = st.tabs(["Sign in", "Create account"])
    with login_tab:
        with st.form("login"):
            username = st.text_input("Email or username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            user_id = database.authenticate_user(username, password)
            if user_id is None:
                st.error("Incorrect username or password.")
            else:
                st.session_state.auth_user_id = user_id
                st.session_state.auth_name = username.strip()
                st.rerun()
        if st.button("Forgot password?", key="forgot_password"):
            st.session_state.password_reset = {"stage": "request"}
            st.rerun()
    with register_tab:
        pending = st.session_state.get("pending_registration")
        if not pending:
            with st.form("register"):
                username = st.text_input("Choose a username", key="register_username")
                email = st.text_input("Email address", key="register_email")
                password = st.text_input("Create a password", type="password", key="register_password")
                confirm = st.text_input("Confirm password", type="password", key="register_confirm")
                submitted = st.form_submit_button("Send verification OTP", type="primary", use_container_width=True)
            if submitted:
                if password != confirm:
                    st.error("The passwords do not match.")
                elif not username.strip() or "@" not in email:
                    st.error("Enter a username and a valid email address.")
                else:
                    otp = auth_helpers.create_otp()
                    try:
                        _send_otp_email(email.strip(), otp)
                    except (OSError, smtplib.SMTPException) as error:
                        st.error(f"Could not send the verification email: {error}")
                        st.info("Configure SMTP email delivery, then try registration again.")
                        return
                    st.session_state.pending_registration = {
                        "username": username.strip(),
                        "email": email.strip().lower(),
                        "password": password,
                        "otp_hash": auth_helpers.hash_otp(otp),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                    }
                    st.rerun()
        else:
            st.info(f"We sent a 6-digit verification code to {pending['email']}.")
            with st.form("verify_registration"):
                otp = st.text_input("Verification OTP", max_chars=6)
                verified = st.form_submit_button("Verify and create account", type="primary", use_container_width=True)
            if verified:
                expired = datetime.now(timezone.utc) >= datetime.fromisoformat(pending["expires_at"])
                if expired:
                    st.error("This OTP has expired. Start registration again.")
                elif not secrets.compare_digest(auth_helpers.hash_otp(otp), pending["otp_hash"]):
                    st.error("Incorrect OTP.")
                else:
                    user_id, error = database.create_login_user(
                        pending["username"], pending["email"], pending["password"]
                    )
                    if error:
                        st.error(error)
                    else:
                        st.session_state.pop("pending_registration", None)
                        st.session_state.auth_user_id = user_id
                        st.session_state.auth_name = pending["username"]
                        st.rerun()
            if st.button("Start registration again"):
                st.session_state.pop("pending_registration", None)
                st.rerun()

    if st.session_state.get("password_reset"):
        password_reset_view()


def password_reset_view():
    reset_state = st.session_state.password_reset
    st.divider()
    st.subheader("Reset your password")
    if reset_state["stage"] == "request":
        with st.form("password_reset_request"):
            identifier = st.text_input("Registered email or username")
            requested = st.form_submit_button("Send reset OTP", type="primary")
        if requested:
            user = database.find_user_for_password_reset(identifier)
            if not user or not user["email"]:
                logger.info(
                    "Password reset not sent: account not eligible or not found "
                    "(identifier_type=%s, user_found=%s, email_present=%s)",
                    "email" if "@" in identifier else "username",
                    bool(user),
                    bool(user and user["email"]),
                )
                st.info("If an account matches those details, a password reset code has been sent.")
            else:
                otp = auth_helpers.create_otp()
                try:
                    _send_password_reset_email(user["email"], user["name"], otp)
                except (OSError, smtplib.SMTPException) as error:
                    logger.exception(
                        "Password reset email failed for an eligible account "
                        "(user_id=%s, recipient_domain=%s)",
                        user["user_id"],
                        user["email"].split("@", 1)[1] if "@" in user["email"] else "unknown",
                    )
                    st.error(f"Could not send the password reset email: {error}")
                else:
                    st.session_state.password_reset = {
                        "stage": "verify",
                        "user_id": int(user["user_id"]),
                        "email": user["email"],
                        "username": user["name"],
                        "otp_hash": auth_helpers.hash_otp(otp),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                        "send_count": 1,
                    }
                    st.rerun()
        if st.button("Back to sign in", key="reset_back_request"):
            st.session_state.pop("password_reset", None)
            st.rerun()
    elif reset_state["stage"] == "verify":
        st.info(f"Enter the 6-digit code sent to {reset_state['email']}. It expires in 5 minutes.")
        with st.form("password_reset_verify"):
            otp = st.text_input("Verification OTP", max_chars=6)
            verified = st.form_submit_button("Verify OTP", type="primary")
        if verified:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(reset_state["expires_at"]):
                st.error("This OTP has expired. Request a new code.")
            elif not secrets.compare_digest(auth_helpers.hash_otp(otp), reset_state["otp_hash"]):
                st.error("Incorrect OTP.")
            else:
                reset_state["stage"] = "new_password"
                st.rerun()
        if reset_state["send_count"] < 3 and st.button("Resend OTP", key="reset_resend"):
            otp = auth_helpers.create_otp()
            try:
                _send_password_reset_email(reset_state["email"], reset_state["username"], otp)
            except (OSError, smtplib.SMTPException) as error:
                logger.exception(
                    "Password reset resend failed (user_id=%s, send_count=%s)",
                    reset_state["user_id"],
                    reset_state["send_count"],
                )
                st.error(f"Could not resend the password reset email: {error}")
            else:
                reset_state.update(
                    otp_hash=auth_helpers.hash_otp(otp),
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    send_count=reset_state["send_count"] + 1,
                )
                st.success("A new reset code has been sent.")
                st.rerun()
        elif reset_state["send_count"] >= 3:
            st.caption("Maximum resend attempts reached. Start again later.")
        if st.button("Cancel password reset", key="reset_cancel_verify"):
            st.session_state.pop("password_reset", None)
            st.rerun()
    else:
        with st.form("new_password"):
            new_password = st.text_input("New password", type="password")
            confirm_password = st.text_input("Confirm new password", type="password")
            changed = st.form_submit_button("Change password", type="primary")
        if changed:
            if len(new_password) < 6:
                st.error("Password must be at least 6 characters.")
            elif new_password != confirm_password:
                st.error("The passwords do not match.")
            else:
                database.update_user_password(reset_state["user_id"], new_password)
                st.session_state.pop("password_reset", None)
                st.success("Password changed successfully. You can now sign in.")
        if st.button("Cancel password reset", key="reset_cancel_password"):
            st.session_state.pop("password_reset", None)
            st.rerun()


def _send_otp_email(recipient: str, otp: str) -> None:
    secrets_values = _streamlit_smtp_secrets()
    smtp = auth_helpers.smtp_config(secrets_values)
    auth_helpers.send_otp(
        recipient=recipient,
        code=otp,
        smtp=smtp,
    )


def _send_password_reset_email(recipient: str, username: str, otp: str) -> None:
    smtp = auth_helpers.smtp_config(_streamlit_smtp_secrets())
    auth_helpers.send_password_reset_otp(
        recipient=recipient, username=username, code=otp, smtp=smtp
    )


def _streamlit_smtp_secrets() -> dict[str, object]:
    """Read each root-level SMTP secret explicitly without exposing values."""
    names = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")
    try:
        return {name: st.secrets[name] for name in names}
    except (FileNotFoundError, KeyError):
        return {}


def setup_view():
    st.markdown(
        '<div class="hero"><h1>🎯 Your next interview starts here</h1>'
        '<p>Practice with a personal AI interviewer, improve your answers, and build confidence one conversation at a time.</p></div>',
        unsafe_allow_html=True,
    )
    f1, f2, f3 = st.columns(3)
    f1.markdown('<div class="feature-card"><strong>🎙️ Real conversation</strong><span>Speak naturally with hands-free voice mode and live camera practice.</span></div>', unsafe_allow_html=True)
    f2.markdown('<div class="feature-card"><strong>🧠 Personal coaching</strong><span>Get targeted feedback, follow-up questions, and practical next steps.</span></div>', unsafe_allow_html=True)
    f3.markdown('<div class="feature-card"><strong>📈 Track your growth</strong><span>Save your attempts and see how your interview performance improves.</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-card"><h3>Build your practice session</h3><p class="muted">Tell the coach what you want to practise. You can change these settings for every attempt.</p></div>', unsafe_allow_html=True)
    with st.form("setup"):
        name = st.text_input("👋 What should the interviewer call you?", value=st.session_state.get("auth_name", ""), placeholder="Enter your name")
        c1, c2 = st.columns(2)
        role = c1.text_input("🎯 Target role", "Software Engineer")
        level = c2.selectbox("📊 Experience level", ["Entry level", "Mid level", "Senior", "Staff / Lead"])
        c3, c4 = st.columns(2)
        interview_type = c3.selectbox("🧭 Interview focus", ["Mixed", "Technical", "Behavioral"])
        count = c4.slider("📝 Starting questions", 3, 10, 5)
        topics = st.multiselect(
            "💻 What would you like to practise?",
            ai_service.TOPICS,
            default=["Python", "APIs"],
            help="Choose one or more technologies. Questions are rotated across your previous attempts.",
        )
        mode_col, lang_col = st.columns(2)
        adaptive_mode = st.checkbox(
            "Adaptive interviewer mode",
            value=True,
            help="The coach asks follow-up questions based on your answers. Use Finish interview when you are ready.",
        )
        live_mode = st.checkbox(
            "🎙️ Live interview mode (hands-free)",
            value=True,
            help="The browser speaks each question, listens until you pause, evaluates your answer, and continues automatically.",
        )
        language = lang_col.selectbox(
            "Speech recognition language",
            ["English (India)", "English (US)", "English (UK)"],
            help="Choose the accent/language used to transcribe your microphone answer.",
        )
        mode_col.caption("The coach will ask follow-up questions based on your answers.")
        with st.expander("Advanced AI settings"):
            model_choice = st.selectbox(
                "Ollama model",
                [
                    "llama3.2",
                    "llama3.1",
                    "mistral",
                    "gemma2",
                    "qwen2.5",
                    "phi3",
                    "deepseek-r1",
                    "codellama",
                    "Custom model",
                ],
                help="Choose a local model installed in Ollama. If it is not installed, the app uses its fallback mode.",
            )
            model = (
                st.text_input("Custom Ollama model name", "llama3.2")
                if model_choice == "Custom model"
                else model_choice
            )
            st.caption("Install a model with `ollama pull <model-name>` before using it.")
        submitted = st.form_submit_button("Submit Details", type="primary", use_container_width=True)
    if submitted:
        if not name.strip() or not role.strip():
            st.error("Please provide your name and target role.")
            return
        st.session_state.setup_details = {
            "name": name.strip(),
            "role": role.strip(),
            "level": level,
            "interview_type": interview_type,
            "count": count,
            "topics": topics,
            "adaptive_mode": adaptive_mode,
            "live_mode": live_mode,
            "language": language,
            "model": model,
        }
        st.session_state.setup_submitted = True
        st.session_state.camera_confirmed = False
        st.session_state.voice_test_passed = False
        st.session_state.pop("voice_test_text", None)
        st.session_state.pop("voice_test_error", None)
        st.rerun()


def camera_precheck_view():
    details = st.session_state.setup_details
    st.markdown(
        '<div class="hero"><h1>📹 Camera & Voice Pre-check</h1>'
        '<p>Camera and microphone access are required before your interview can begin. Test both, then confirm you are ready.</p></div>',
        unsafe_allow_html=True,
    )
    st.subheader("📹 Camera preview")
    st.caption("Click START, allow browser camera permission, and use SELECT DEVICE in the camera control when multiple cameras are available.")
    camera_ready = False
    if hasattr(capture, "camera_precheck"):
        camera_event = capture.camera_precheck()
        camera_ready = camera_event.get("status") == "active"
        if camera_ready:
            st.success("Camera is active and ready.")
        elif camera_event.get("status") == "error":
            st.error(camera_event.get("error", "Camera could not be started."))
        else:
            st.info("Click START on the camera preview and allow browser camera permission.")
    else:
        camera_photo = st.camera_input("Camera preview", key="camera_precheck_photo")
        camera_ready = camera_photo is not None
        if not camera_ready:
            st.warning("No live camera component is available. Allow camera access and take a preview photo.")
    st.session_state.camera_confirmed = st.checkbox(
        "I have checked my camera framing, lighting, and eye contact.",
        disabled=not camera_ready,
        value=st.session_state.get("camera_confirmed", False),
        key="camera_check_confirmation",
    )
    st.subheader("🎙️ Voice pre-check")
    st.caption("Click START VOICE TEST, speak a short sentence, and stop recording. Your speech must be recognized before you can start.")
    voice_available, voice_message = capture.available()
    voice_recording = None
    if voice_available:
        voice_recording = capture.audio_input(
            "precheck_voice",
            start_prompt="START VOICE TEST",
            stop_prompt="STOP VOICE TEST",
        )
        if voice_recording and voice_recording.get("bytes"):
            st.caption(
                f"Recorded format: {voice_recording.get('format', 'unknown')} "
                f"({len(voice_recording['bytes'])} bytes)"
            )
            language_code = {
                "English (India)": "en-IN",
                "English (US)": "en-US",
                "English (UK)": "en-GB",
            }.get(details["language"], "en-IN")
            with st.spinner("Recognizing your voice..."):
                transcript, error = capture.transcribe_audio(
                    voice_recording["bytes"], language_code
                )
            if transcript:
                st.session_state.voice_test_passed = True
                st.session_state.voice_test_text = transcript
                st.session_state.pop("voice_test_error", None)
            else:
                st.session_state.voice_test_passed = False
                st.session_state.voice_test_error = error or "Speech was not recognized."
        if st.session_state.get("voice_test_passed"):
            st.success("Voice test passed.")
            st.info(f"Recognized speech: {st.session_state.voice_test_text}")
        elif st.session_state.get("voice_test_error"):
            st.error(st.session_state.voice_test_error)
            st.caption("Try the voice test again and speak clearly for a few seconds.")
    else:
        st.warning(f"Voice test unavailable: {voice_message}")
    can_start = (
        camera_ready
        and st.session_state.camera_confirmed
        and st.session_state.get("voice_test_passed", False)
    )
    if can_start:
        st.success("Camera and voice pre-checks passed. You can start the interview.")
    if st.button("🚀 Start your interview", type="primary", use_container_width=True, disabled=not can_start):
        with st.spinner("Preparing your interview..."):
            user_id = st.session_state.get("auth_user_id") or database.get_or_create_user(details["name"])
            session_id = database.create_session(
                user_id, details["role"], details["level"], details["interview_type"],
                details["count"], details["topics"],
            )
            questions = ai_service.generate_questions(
                details["role"], details["level"], details["interview_type"], details["count"],
                details["model"], details["topics"], database.prior_questions(user_id),
                use_ai=not details["live_mode"],
            )
            if questions:
                questions[0] = opening_question(details["name"], details["role"])
            database.save_questions(session_id, questions)
        st.session_state.update(
            session_id=session_id, questions=questions, current=0, evaluations=[],
            model=details["model"], role=details["role"], name=details["name"],
            topics=details["topics"], initial_count=details["count"],
            adaptive_mode=details["adaptive_mode"], live_mode=details["live_mode"],
            language=details["language"], live_transcript=[], live_last_event=None,
            live_replay=0, welcome_played=False,
        )
        st.session_state.pop("setup_details", None)
        st.session_state.pop("setup_submitted", None)
        st.session_state.pop("camera_confirmed", None)
        st.session_state.pop("voice_test_passed", None)
        st.session_state.pop("voice_test_text", None)
        st.session_state.pop("voice_test_error", None)
        st.rerun()
    if st.button("← Edit interview details", key="edit_setup"):
        st.session_state.pop("setup_details", None)
        st.session_state.pop("setup_submitted", None)
        st.session_state.pop("camera_confirmed", None)
        st.session_state.pop("voice_test_passed", None)
        st.session_state.pop("voice_test_text", None)
        st.session_state.pop("voice_test_error", None)
        st.rerun()


def interview_view():
    questions = st.session_state.questions
    index = st.session_state.current
    st.progress(index / len(questions), text=f"Question {index + 1} of {len(questions)}")
    st.header("Your interview")
    st.caption(f"Target role: {st.session_state.role} • Topics: {', '.join(st.session_state.topics)} • Take your time and answer naturally.")
    if index == 0:
        st.chat_message("assistant", avatar="🎙️").write(
            f"Hi {st.session_state.name}! Welcome to your interview. "
            "I’ll ask you questions one at a time and give you coaching after each answer."
        )
        if st.button("🔊 Hear welcome", key="hear_welcome"):
            welcome_audio = capture.question_audio(
                f"Hi {st.session_state.name}! Welcome to your interview. "
                "To get started, please tell me about yourself, your background, "
                "and the kind of work you enjoy."
            )
            if welcome_audio:
                st.audio(welcome_audio, format="audio/mp3")
            else:
                st.info("Welcome audio is unavailable. You can read the interviewer message above.")
    if st.session_state.get("adaptive_mode") and st.button("Finish interview and show report", key=f"finish_{index}"):
        if st.session_state.evaluations:
            st.session_state.current = len(st.session_state.questions)
            st.rerun()
        st.info("Answer at least one question before finishing.")
    question = questions[index]
    st.markdown(f"### {question}")
    if st.session_state.get("live_mode"):
        st.markdown(
            '<div class="live-shell"><div class="live-kicker">Hands-free interview</div>'
            '<span class="live-status"><span class="live-status-dot"></span>Live conversation enabled</span></div>',
            unsafe_allow_html=True,
        )
        main_col, camera_col = st.columns([1.55, 1], gap="large")
        with main_col:
            st.markdown("#### 🎙️ Interviewer is asking")
            st.markdown(
                f'<div class="live-question-card">{html.escape(question)}</div>',
                unsafe_allow_html=True,
            )
            st.caption("Your turn — speak your answer when the interviewer finishes.")
            if st.session_state.get("live_transcript"):
                st.markdown("#### Conversation history")
                for item in st.session_state.get("live_transcript", []):
                    st.markdown(
                        f'<div class="live-history-card"><strong style="color:#a5b4fc;">Interviewer</strong>'
                        f'<div style="margin:.35rem 0 .7rem;color:#e2e8f0;">{html.escape(item["question"])}</div>'
                        f'<strong style="color:#86efac;">You</strong>'
                        f'<div style="margin:.35rem 0;color:#cbd5e1;">{html.escape(item["answer"])}</div>'
                        f'<small style="color:#94a3b8;">Coach score: {item["evaluation"]["score"]}/10 · '
                        f'{html.escape(item["evaluation"]["feedback"])}</small></div>',
                        unsafe_allow_html=True,
                    )
        with camera_col:
            st.markdown("#### Camera & microphone")
            st.caption("Your camera preview is mirrored for a natural self-view.")
            live_interview_parameters = {
                "greeting": f"Hi {st.session_state.name}, welcome to your interview." if index == 0 else "",
                "replay": st.session_state.get("live_replay", 0),
                "key": "live_interview",
            }
            live_language = {
                "English (India)": "en-IN",
                "English (US)": "en-US",
                "English (UK)": "en-GB",
            }.get(st.session_state.get("language"), "en-IN")
            if "language" in inspect.signature(live_interview).parameters:
                live_interview_parameters["language"] = live_language
            event = live_interview(question, **live_interview_parameters)
            st.caption("Supported in current Chrome or Edge. Headphones reduce echo.")
        if event and event.get("type") == "answer" and event.get("at") != st.session_state.get("live_last_event"):
            answer = event.get("text", "").strip()
            if not answer and event.get("audio"):
                with st.spinner("Converting your answer to text…"):
                    language_code = {
                        "English (India)": "en-IN",
                        "English (US)": "en-US",
                        "English (UK)": "en-GB",
                    }.get(st.session_state.get("language"), "en-IN")
                    answer, transcription_error = capture.transcribe_base64_wav(event["audio"], language_code)
                if not answer:
                    st.warning(transcription_error or "I could not transcribe that recording. Please try again.")
            st.session_state.live_last_event = event.get("at")
            if answer:
                command = " ".join(answer.casefold().replace("please", "").split())
                if command in {
                    "repeat",
                    "repeat again",
                    "say that again",
                    "say it again",
                    "can you repeat",
                    "i did not hear",
                    "i didn't hear",
                    "could you repeat",
                }:
                    st.session_state.live_replay = st.session_state.get("live_replay", 0) + 1
                    st.session_state.live_last_event = None
                    st.rerun()
                with st.spinner("Evaluating your answer…"):
                    evaluation = ai_service.evaluate_answer(
                        question, answer, st.session_state.model, fast=True
                    )
                question_rows = database.get_questions(st.session_state.session_id)
                database.save_answer(question_rows[index]["question_id"], {"answer": answer, **evaluation})
                st.session_state.evaluations.append(evaluation)
                st.session_state.live_transcript.append({"question": question, "answer": answer, "evaluation": evaluation})
                follow_up = evaluation.get("follow_up_question")
                max_questions = 50 if st.session_state.get("adaptive_mode") else 2 * st.session_state.initial_count
                if follow_up and len(st.session_state.questions) < max_questions:
                    database.save_question(st.session_state.session_id, follow_up)
                    st.session_state.questions.append(follow_up)
                st.session_state.current += 1
                st.rerun()
        if st.button("Stop live mode and switch to typed answers", key=f"stop_live_{index}"):
            st.session_state.live_mode = False
            st.rerun()
        return
    if st.button("🔊 Hear question", key=f"speak_{index}"):
        with st.spinner("Preparing audio..."):
            question_audio = capture.question_audio(question)
        if question_audio:
            st.audio(question_audio, format="audio/mp3")
        else:
            st.info("Question audio is unavailable. You can read the text above.")
    pending_transcript = st.session_state.pop(f"transcript_{index}", None)
    if pending_transcript:
        st.session_state[f"answer_{index}"] = pending_transcript
    answer = st.text_area("Type your answer", height=190, placeholder="Structure your response with context, actions, and outcomes.", key=f"answer_{index}")
    audio_ok, audio_message = capture.available()
    with st.expander("Optional camera / audio capture"):
        st.caption("Camera guidance: use the preview to self-check upright posture, framing, and natural eye contact with the camera. "
                   "This app does not claim to perform eye tracking or assess appearance.")
        if WEBRTC_AVAILABLE:
            capture.live_stream(f"live_{index}")
        else:
            st.camera_input("Camera preview", key=f"camera_{index}")
            st.info("Install streamlit-webrtc for a live camera/microphone preview.")
        if audio_ok:
            recording = capture.audio_input(f"audio_{index}")
            if recording and recording.get("bytes"):
                st.success("Audio captured.")
                if st.button("Transcribe recording", key=f"transcribe_{index}"):
                    with st.spinner("Transcribing..."):
                        language_code = {
                            "English (India)": "en-IN",
                            "English (US)": "en-US",
                            "English (UK)": "en-GB",
                        }.get(st.session_state.get("language"), "en-IN")
                        text, error = capture.transcribe_audio(recording["bytes"], language_code)
                    if text:
                        st.session_state[f"transcript_{index}"] = text
                        st.success("Transcript added to the answer box.")
                        st.rerun()
                    st.warning(error or "Could not transcribe audio.")
        else:
            st.info(audio_message)
        st.checkbox("I reviewed my posture, eye contact, and speaking pace.", key=f"reviewed_{index}")
    if st.button("Submit answer →", type="primary", disabled=not answer.strip()):
        with st.spinner("Analyzing your answer..."):
            evaluation = ai_service.evaluate_answer(question, answer, st.session_state.model)
        question_rows = database.get_questions(st.session_state.session_id)
        database.save_answer(question_rows[index]["question_id"], {"answer": answer, **evaluation})
        st.session_state.evaluations.append(evaluation)
        follow_up = evaluation.get("follow_up_question")
        max_questions = 50 if st.session_state.get("adaptive_mode") else 2 * st.session_state.initial_count
        if follow_up and len(st.session_state.questions) < max_questions:
            database.save_question(st.session_state.session_id, follow_up)
            st.session_state.questions.append(follow_up)
        st.session_state.current += 1
        st.rerun()


def report_view():
    if "report" not in st.session_state:
        with st.spinner("Building your coaching report..."):
            report = ai_service.build_report(st.session_state.evaluations, st.session_state.model)
            database.finish_session(st.session_state.session_id, report)
            st.session_state.report = report
    report = st.session_state.report
    st.balloons()
    st.markdown('<div class="hero"><h1>Interview complete 🎉</h1><p>Here is your personalized practice report.</p></div>', unsafe_allow_html=True)
    st.metric("Overall score", f"{report['overall_score']}/10")
    c1, c2, c3 = st.columns(3)
    c1.subheader("Strengths")
    c1.markdown("\n".join(f"- {item}" for item in report["strengths"]))
    c2.subheader("Growth areas")
    c2.markdown("\n".join(f"- {item}" for item in report["weaknesses"]))
    c3.subheader("Next steps")
    c3.markdown("\n".join(f"- {item}" for item in report["recommendations"]))
    st.subheader("Answer-by-answer coaching")
    for number, (question, evaluation) in enumerate(zip(st.session_state.questions, st.session_state.evaluations), 1):
        with st.expander(f"{number}. {question} — {evaluation['score']}/10"):
            st.write(evaluation["feedback"])
            st.caption(f"Try this: {evaluation['suggestion']}")
    if st.button("Start another interview", type="primary"):
        reset()
        st.rerun()


def dashboard():
    if "auth_user_id" not in st.session_state:
        return
    st.sidebar.title("Interview Coach")
    st.sidebar.caption(f"Signed in as **{st.session_state.get('auth_name', 'candidate')}**")
    if st.sidebar.button("Sign out", use_container_width=True):
        reset()
        st.session_state.pop("auth_user_id", None)
        st.session_state.pop("auth_name", None)
        st.rerun()
    if st.sidebar.button("＋ New interview", use_container_width=True):
        reset()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.subheader("Recent progress")
    rows = database.history(user_id=st.session_state.auth_user_id)
    if not rows:
        st.sidebar.caption("Complete your first interview to see progress here.")
    for row in rows:
        st.sidebar.write(f"**{row['overall_score']:.1f}/10** · {row['job_role']}")
        st.sidebar.caption(row["created_at"][:10])


if "auth_user_id" not in st.session_state:
    login_view()
else:
    dashboard()
    if "session_id" not in st.session_state:
        if st.session_state.get("setup_submitted") and st.session_state.get("setup_details"):
            camera_precheck_view()
        else:
            setup_view()
    elif st.session_state.current < len(st.session_state.questions):
        interview_view()
    else:
        report_view()
