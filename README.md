# Interview Coach

A polished Streamlit practice interviewer backed by SQLite. It generates topic-focused questions, evaluates answers, asks adaptive follow-ups,
and stores a personalized progress report. Ollama is optional: without it, the
app uses rotating local question pools and scoring so the complete flow still works.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Open the displayed local URL. The SQLite file `interview_coach.db` is created automatically.

## Sign in and camera pre-check

The app opens with a local sign-in page. Create an account once, verify the
email OTP, then sign in to keep your interview history and progress associated
with your profile. Passwords are stored as salted PBKDF2 hashes in the local
SQLite database.

Email OTP delivery requires SMTP configuration before account registration:

```powershell
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="your-gmail-address@gmail.com"
$env:SMTP_PASSWORD="your-16-character-gmail-app-password"
$env:SMTP_FROM="your-gmail-address@gmail.com"
streamlit run app.py
```

For Gmail, enable 2-Step Verification and create an **App Password** at
`myaccount.google.com/apppasswords`; do not use your normal Gmail password.
The variables must be set in the same terminal from which Streamlit is
started. Alternatively, copy `.streamlit/secrets.example.toml` to
`.streamlit/secrets.toml` (do not commit the latter) and replace the
placeholders:

```toml
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "587"
SMTP_USERNAME = "your-gmail-address@gmail.com"
SMTP_PASSWORD = "your-16-character-gmail-app-password"
SMTP_FROM = "your-gmail-address@gmail.com"
```

For Gmail, use the 16-character Google App Password without spaces in
`SMTP_PASSWORD`. Restart Streamlit after changing the secrets file. The
application reads environment variables first and uses Streamlit secrets as
the local-development fallback; it never displays these values in the UI.

The OTP is never displayed in the app. It is delivered privately to the
entered email address, which you can open on your phone. Registration remains
blocked until SMTP is configured and the email is sent successfully.

Camera access is mandatory before an interview can start. On the setup page,
click **START** in the camera pre-check, allow browser camera permission,
check your framing and lighting, and confirm the pre-check. The **Start my
interview** button remains disabled until this is complete.

## Optional AI

Install [Ollama](https://ollama.com), start it, and pull a model:

```powershell
ollama serve
ollama pull llama3.2
```

Set `OLLAMA_HOST` if Ollama is running elsewhere. You can choose from the
available local models in Advanced AI settings, or enter a custom model name.

## Topics and question rotation

Choose one or more technologies/topics (Python, Java, JavaScript, HTML, CSS, C,
Databases, APIs, system design, cloud, testing, or data structures). Previous
questions for the same user are sent as exclusions to Ollama and are also
filtered from the local fallback pool, so repeated practice sessions keep
rotating. Each submitted answer can produce one targeted follow-up question.

## Video, audio, and speech

During an interview, open **Optional camera / audio capture** and allow the
browser to use your webcam and microphone. `streamlit-webrtc` provides a live
camera/microphone preview. The **Record answer** control (from
`streamlit-mic-recorder`) records a short response, and **Transcribe
recording** uses Google Speech Recognition through `SpeechRecognition`.
Transcription requires an internet connection and may fail for noisy audio;
the answer can always be typed or edited in the text box.

The camera preview is an optional self-check for posture, framing, and looking
naturally toward the camera. It is guidance only: the app does not perform or
claim to perform eye tracking.

Use **Live hands-free mode** for a continuous interviewer conversation. The
agent speaks the current question, keeps the microphone open, detects when you
stop speaking, transcribes the answer, evaluates it, and advances
automatically. A first click is still required by Chrome/Edge to grant
microphone permission. Headphones are recommended so the agent's voice is not
captured as your answer.

You can say **“repeat”**, **“repeat again”**, **“say that again”**, or
**“I did not hear”** to replay the current question without submitting it.
The exact interviewer message remains visible on screen while the live
conversation runs. If speech recognition is unavailable or audio is unclear,
the typed-answer workflow remains available.
