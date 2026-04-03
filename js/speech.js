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
        const langPrefix = langCode.split('-')[0];
        const matchingVoices = voices.filter(v => v.lang.startsWith(langPrefix));

        // Rank voices by quality: Natural/Premium > specific named voices > Google > any
        const preferredVoice = matchingVoices.find(v =>
            v.name.includes('Natural') || v.name.includes('Premium')
        ) || matchingVoices.find(v =>
            v.name.includes('Samantha') || v.name.includes('Karen') || v.name.includes('Daniel')
        ) || matchingVoices.find(v =>
            v.name.includes('Google') || v.name.includes('Enhanced')
        ) || matchingVoices[0];

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
