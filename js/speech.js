import './state.js';

// Speak a word in the target language
function speakWord(text, useEnglish = false) {
    if (!speechEnabled || !text || !window.speechSynthesis) return;

    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    const langCode = useEnglish ? 'en-GB' : (speechLangCodes[selectedLanguage] || 'es-ES');
    utterance.lang = langCode;
    utterance.rate = 0.9; // Slightly slower for learning

    // Try to find a better quality voice
    const voices = window.speechSynthesis.getVoices();
    if (voices.length > 0) {
        // Prefer Google or premium voices, then any matching voice
        const preferredVoice = voices.find(v =>
            v.lang.startsWith(langCode.split('-')[0]) &&
            (v.name.includes('Google') || v.name.includes('Premium') || v.name.includes('Enhanced') || v.name.includes('Samantha') || v.name.includes('Daniel'))
        ) || voices.find(v => v.lang.startsWith(langCode.split('-')[0]));

        if (preferredVoice) {
            utterance.voice = preferredVoice;
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
