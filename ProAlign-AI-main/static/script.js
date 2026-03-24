// Stop voice when page changes
window.addEventListener("beforeunload", function () {
    window.speechSynthesis.cancel();
});
/* ===================================================
   PROALIGN AI - GLOBAL SCRIPT
   =================================================== */

/* =========================
   GLOBAL VARIABLES
========================= */

let currentAnswer = "";
let interviewStarted = false;
let totalQuestions = 5;

/* =========================
   SPEAK FUNCTION
========================= */

function speak(text, callback = null) {

    // STOP previous speech
    window.speechSynthesis.cancel();

    const speech = new SpeechSynthesisUtterance(text);
    speech.lang = "en-US";
    speech.rate = 1;
    speech.pitch = 1;

    speech.onend = function () {
        if (callback) callback();
    };

    speechSynthesis.speak(speech);
}

/* =========================
   INTERVIEW INIT
========================= */

document.addEventListener("DOMContentLoaded", function () {

    const introTextElement = document.getElementById("introText");
    document.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", function() {
        window.speechSynthesis.cancel();
    });
});
    // Only run interview logic if interview page exists
    if (introTextElement) {

        const userName = introTextElement.dataset.name;
        const role = introTextElement.dataset.role;

        const introMessage =
            `Hello ${userName}. You have chosen the role of ${role}. This interview consists of 5 questions.`;

        introTextElement.innerText = introMessage;

        speak(introMessage);

        document.getElementById("proceedBtn").addEventListener("click", function () {

            this.style.display = "none";
            document.getElementById("questionSection").style.display = "block";

            interviewStarted = true;

            loadQuestion();
        });

        // Start camera
        startCamera();
    }

    // Password validation (Signup page)
    passwordValidationInit();
});

/* =========================
   LOAD QUESTION
========================= */

async function loadQuestion() {

    const res = await fetch("/get_question");
    const data = await res.json();

    if (data.question) {

        document.getElementById("question").innerText = data.question;
        if (interviewStarted) {
            window.speechSynthesis.cancel();
            speak(data.question);
        }

    } else {

        finishInterview();
    }
}

/* =========================
   SPEECH RECOGNITION
========================= */

function startRecording() {

    if (!('webkitSpeechRecognition' in window)) {
        alert("Use Google Chrome for speech recognition.");
        return;
    }

    const recognition = new webkitSpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.start();

    recognition.onresult = function (event) {
        currentAnswer = event.results[0][0].transcript;
        document.getElementById("answerText").innerText = currentAnswer;
    };
}

/* =========================
   SUBMIT ANSWER
========================= */

async function submitAnswer() {

    if (!currentAnswer.trim()) {
        alert("Please answer first.");
        return;
    }

    const res = await fetch("/submit_answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: currentAnswer })
    });

    const data = await res.json();

    const list = document.getElementById("answerList");

    if (list) {
        const item = document.createElement("div");
        item.className = "history-item";
        item.innerHTML = `<p>${currentAnswer}</p>`;
        list.appendChild(item);
    }

    currentAnswer = "";
    document.getElementById("answerText").innerText = "";

    if (data.status === "next") {
    loadQuestion();
    } else {
    window.location.href = "/report";
    }
}

/* =========================
   FINISH INTERVIEW
========================= */

function finishInterview() {

    window.speechSynthesis.cancel();

    interviewStarted = false;

    const introTextElement = document.getElementById("introText");

    if (!introTextElement) return;

    const role = introTextElement.dataset.role;

    const endMessage =
        `Thank you for attempting the ${role} role. Redirecting you to home page.`;

    document.getElementById("questionSection").style.display = "none";
    introTextElement.innerText = endMessage;

    speak(endMessage);

    setTimeout(() => {
        window.location.href = "/home";
    }, 4000);
}

/* =========================
   CAMERA
========================= */

function startCamera() {

    const video = document.getElementById("video");

    if (!video) return;

    navigator.mediaDevices.getUserMedia({ video: true })
        .then(stream => {
            video.srcObject = stream;
        })
        .catch(err => console.log("Camera error:", err));
}

/* =========================
   EMOTION TRACKING
========================= */

setInterval(() => {

    if (!interviewStarted) return;

    const video = document.getElementById("video");
    if (!video || !video.videoWidth) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0);

    const imageData = canvas.toDataURL("image/jpeg");

    fetch("/analyze_frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: imageData })
    })
    .then(res => res.json())
    .then(data => {

        const emotionEl = document.getElementById("emotionScore");
        const postureEl = document.getElementById("postureScore");

        if (emotionEl && data.emotion_score !== undefined) {
            emotionEl.innerText = data.emotion_score;
        }

        if (postureEl && data.posture_score !== undefined) {
            postureEl.innerText = data.posture_score;
        }
    });

}, 4000);

/* =========================
   PASSWORD VALIDATION
========================= */

function passwordValidationInit() {

    const passwordInput = document.getElementById("password");
    if (!passwordInput) return;

    passwordInput.addEventListener("input", function () {
        const value = passwordInput.value;

        updateRule("length", value.length >= 8);
        updateRule("upper", /[A-Z]/.test(value));
        updateRule("lower", /[a-z]/.test(value));
        updateRule("number", /[0-9]/.test(value));
        updateRule("special", /[@$!%*?&]/.test(value));
    });
}

function updateRule(id, condition) {

    const rule = document.getElementById(id);
    if (!rule) return;

    if (condition) {
        rule.classList.add("valid");
    } else {
        rule.classList.remove("valid");
    }
}