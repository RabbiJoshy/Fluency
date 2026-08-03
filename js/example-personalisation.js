const RECENT_MISTAKE_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

function normaliseWord(value) {
    return String(value || '').trim().toLocaleLowerCase('es');
}

export function collectRecentWrongWords(progress, now = Date.now()) {
    const cutoff = now - RECENT_MISTAKE_WINDOW_MS;
    const words = new Set();
    for (const data of Object.values(progress || {})) {
        const lastWrong = data?.lastWrong ? new Date(data.lastWrong).getTime() : 0;
        if (Number(data?.wrong || 0) > 0 && lastWrong > cutoff) {
            const word = normaliseWord(data?.word);
            if (word) words.add(word);
        }
    }
    return words;
}

export function filterPersonalisedExamples(examples, recentWrongWords) {
    const wrongWords = recentWrongWords instanceof Set
        ? recentWrongWords
        : new Set(Array.from(recentWrongWords || [], normaliseWord));
    return (examples || []).filter(example => {
        if (!example?.personalised) return true;
        return wrongWords.has(normaliseWord(example.reinforcement_word));
    });
}

export function exampleReinforcesRecentMistake(example, recentWrongWords) {
    return Boolean(
        example?.personalised
        && recentWrongWords?.has(normaliseWord(example.reinforcement_word))
    );
}
