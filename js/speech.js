import './state.js?v=20260824a';

// Speak a word in the target language. The optional completion callback lets
// lyric autoplay wait for the English sense label before starting its first
// example; ordinary callers remain fire-and-forget.
function speakWord(text, useEnglish = false, onComplete = null) {
    if (!speechEnabled || !text || !window.speechSynthesis) {
        if (typeof onComplete === 'function') onComplete();
        return;
    }

    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    let completed = false;
    const complete = () => {
        if (completed) return;
        completed = true;
        if (typeof onComplete === 'function') onComplete();
    };
    utterance.onend = complete;
    utterance.onerror = complete;
    const langCode = useEnglish ? 'en-US' : (speechLangCodes[selectedLanguage] || 'es-ES');
    utterance.lang = langCode;
    utterance.rate = 0.9;

    const voices = window.speechSynthesis.getVoices();
    if (voices.length > 0) {
        const langPrefix = langCode.split('-')[0];
        // Exclude novelty and character voices that sound bad
        const badVoices = /Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Fred|Good News|Jester|Junior|Organ|Ralph|Superstar|Trinoids|Whisper|Wobble|Zarvox|Eddy|Flo|Grandma|Grandpa|Rocko|Reed|Sandy|Shelley/;
        const matchingVoices = voices.filter(v => v.lang.startsWith(langPrefix) && !badVoices.test(v.name));

        // Tier 1: Premium voices (Natural/Siri/Enhanced)
        // Tier 2: Google voices (Chrome)
        // Tier 3: Best named voices in preference order
        const findByName = (name) => matchingVoices.find(v => v.name.includes(name));
        const preferredVoice = findByName('Natural') || findByName('Premium') || findByName('Siri')
            || findByName('Enhanced')
            || findByName('Google')
            || findByName('Samantha') || findByName('Ava') || findByName('Paulina')
            || findByName('Mónica') || findByName('Kathy') || findByName('Moira')
            || findByName('Karen') || findByName('Tessa')
            || findByName('Daniel') || findByName('Rishi')
            || matchingVoices[0];

        if (preferredVoice) {
            utterance.voice = preferredVoice;
            utterance.lang = preferredVoice.lang;
        }
    }

    window.speechSynthesis.speak(utterance);
}

// Preload voices (they may not be available immediately)
if (window.speechSynthesis) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
    };
}

window.speakWord = speakWord;
