"""Polished Streamlit AI Interview Coach."""

from __future__ import annotations

import os
import secrets
import smtplib
import streamlit as st
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

import ai_service
import capture
import database
from live_interview import live_interview

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
</style>""", unsafe_allow_html=True)


def reset():
    for key in ("session_id", "questions", "current", "evaluations", "report", "submitted", "topics", "initial_count", "adaptive_mode", "live_mode", "live_transcript", "live_last_event", "live_replay"):
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
            username = st.text_input("Username", key="login_username")
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
                    otp = f"{secrets.randbelow(1_000_000):06d}"
                    email_sent = True
                    try:
                        _send_otp_email(email.strip(), otp)
                    except (OSError, smtplib.SMTPException) as error:
                        if "Email is not configured." not in str(error):
                            st.error(f"Could not send the verification email: {error}")
                            email_sent = False
                        else:
                            email_sent = False
                            st.session_state.local_otp = otp
                            st.warning(
                                "SMTP is not configured. Development OTP mode is active; "
                                "use the code shown below. Configure SMTP before deploying this app."
                            )
                    if email_sent:
                        st.session_state.local_otp = None
                    st.session_state.pending_registration = {
                        "username": username.strip(),
                        "email": email.strip().lower(),
                        "password": password,
                        "otp": otp,
                        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                    }
                    st.rerun()
        else:
            st.info(f"We sent a 6-digit verification code to {pending['email']}.")
            if st.session_state.get("local_otp"):
                st.warning(
                    f"Development OTP: **{st.session_state.local_otp}** "
                    "(visible only because SMTP email is not configured)"
                )
            with st.form("verify_registration"):
                otp = st.text_input("Verification OTP", max_chars=6)
                verified = st.form_submit_button("Verify and create account", type="primary", use_container_width=True)
            if verified:
                expired = datetime.now(timezone.utc) >= datetime.fromisoformat(pending["expires_at"])
                if expired:
                    st.error("This OTP has expired. Start registration again.")
                elif not secrets.compare_digest(otp.strip(), pending["otp"]):
                    st.error("Incorrect OTP.")
                else:
                    user_id, error = database.create_login_user(
                        pending["username"], pending["email"], pending["password"]
                    )
                    if error:
                        st.error(error)
                    else:
                        st.session_state.pop("pending_registration", None)
                        st.session_state.pop("local_otp", None)
                        st.session_state.auth_user_id = user_id
                        st.session_state.auth_name = pending["username"]
                        st.rerun()
            if st.button("Start registration again"):
                st.session_state.pop("pending_registration", None)
                st.rerun()


def _send_otp_email(recipient: str, otp: str) -> None:
    def setting(name: str, default: str = "") -> str:
        value = os.getenv(name)
        if value:
            return value
        try:
            return str(st.secrets.get(name, default))
        except (FileNotFoundError, KeyError):
            return default

    host = setting("SMTP_HOST")
    port = int(setting("SMTP_PORT", "587"))
    username = setting("SMTP_USERNAME")
    password = setting("SMTP_PASSWORD")
    sender = setting("SMTP_FROM", username)
    if not host or not username or not password or not sender:
        raise OSError(
            "Email is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, "
            "SMTP_PASSWORD, and SMTP_FROM, then restart Streamlit."
        )
    message = EmailMessage()
    message["Subject"] = "Interview Coach verification code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(f"Your Interview Coach verification code is {otp}. It expires in 10 minutes.")
    if port == 465:
        server_context = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server_context = smtplib.SMTP(host, port, timeout=15)
    with server_context as server:
        if port != 465:
            server.starttls()
        server.login(username, password)
        server.send_message(message)


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
    st.subheader("📹 Camera pre-check")
    st.caption("Camera access is required for every interview. Start the preview, check your framing and lighting, then confirm before continuing.")
    camera_ready = False
    if WEBRTC_AVAILABLE:
        camera_context = capture.live_stream("camera_precheck", audio=False)
        camera_ready = bool(camera_context and camera_context.state.playing)
        if camera_ready:
            st.success("Camera is active and ready.")
        else:
            st.warning("Click START on the camera preview and allow browser camera permission.")
    else:
        camera_photo = st.camera_input("Take a camera check photo", key="camera_precheck_photo")
        camera_ready = camera_photo is not None
        if not camera_ready:
            st.warning("Take a camera check photo before starting the interview.")
    camera_confirmed = st.checkbox(
        "I have checked my camera framing, lighting, and eye contact.",
        disabled=not camera_ready,
        key="camera_confirmed",
    )
    camera_ready = camera_ready and camera_confirmed
    if camera_ready:
        st.success("Camera pre-check passed. You can start the interview.")
    st.markdown('<div class="section-card"><h3>Build your practice session</h3><p class="muted">Tell the coach what you want to practise. You can change these settings for every attempt.</p></div>', unsafe_allow_html=True)
    with st.form("setup"):
        name = st.text_input("👋 What should the interviewer call you?", value=st.session_state.get("auth_name", ""), placeholder="e.g. Bharath")
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
        submitted = st.form_submit_button("🚀 Start my interview", type="primary", use_container_width=True, disabled=not camera_ready)
    if submitted:
        if not camera_ready:
            st.error("Complete the camera pre-check before starting the interview.")
            return
        if not name.strip() or not role.strip():
            st.error("Please provide your name and target role.")
            return
        with st.spinner("Preparing your interview..."):
            user_id = st.session_state.get("auth_user_id") or database.get_or_create_user(name)
            session_id = database.create_session(user_id, role, level, interview_type, count, topics)
            questions = ai_service.generate_questions(
                role, level, interview_type, count, model, topics, database.prior_questions(user_id),
                use_ai=not live_mode,
            )
            if questions:
                questions[0] = opening_question(name, role)
            database.save_questions(session_id, questions)
        st.session_state.update(session_id=session_id, questions=questions, current=0, evaluations=[],
                                model=model, role=role, name=name, topics=topics, initial_count=count,
                                adaptive_mode=adaptive_mode, live_mode=live_mode, language=language, live_transcript=[],
                                live_last_event=None, live_replay=0, welcome_played=False)
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
        st.info("🎙️ **Live interview is on.** Your browser will speak, listen for a pause, and continue without button clicks.")
        st.caption("Supported in Chrome/Edge desktop. Keep your speaker volume moderate and use headphones when possible to prevent the question audio from entering your answer.")
        if WEBRTC_AVAILABLE:
            st.subheader("📹 Your live camera and microphone")
            st.caption("The preview uses video only. The separate recorder uses your microphone once, preventing echo and duplicate words.")
            capture.live_stream("live_camera_preview", audio=False)
        else:
            st.warning("Live camera/microphone preview is unavailable. Install `streamlit-webrtc` to enable it.")
        event = live_interview(
            question,
            greeting=f"Hi {st.session_state.name}, welcome to your interview." if index == 0 else "",
            replay=st.session_state.get("live_replay", 0),
            key="live_interview",
        )
        st.markdown("#### 🎙️ Interviewer is asking")
        st.info(question)
        for item in st.session_state.get("live_transcript", []):
            with st.chat_message("assistant"):
                st.write(item["question"])
            with st.chat_message("user"):
                st.write(item["answer"])
            st.caption(f"Coach score: {item['evaluation']['score']}/10 — {item['evaluation']['feedback']}")
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
        setup_view()
    elif st.session_state.current < len(st.session_state.questions):
        interview_view()
    else:
        report_view()
