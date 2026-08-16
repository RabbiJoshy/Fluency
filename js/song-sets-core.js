export function selectedSongIdSet(catalog, selectedSongIds) {
    const available = new Set((catalog?.songs || []).map(song => String(song.id)));
    const selected = new Set((selectedSongIds || []).map(String).filter(id => available.has(id)));
    return selected.size ? selected : available;
}

export function selectedSongCardIds(catalog, selectedSongIds) {
    const selected = selectedSongIdSet(catalog, selectedSongIds);
    const cardIds = new Set();
    for (const song of catalog?.songs || []) {
        if (!selected.has(String(song.id))) continue;
        for (const cardId of song.cardIds || []) cardIds.add(String(cardId));
    }
    return cardIds;
}

export function filterVocabularyForSongs(vocabulary, catalog, selectedSongIds) {
    if (!catalog?.songs?.length) return vocabulary;
    const selected = selectedSongIdSet(catalog, selectedSongIds);
    if (selected.size === catalog.songs.length) return vocabulary;
    const cardIds = selectedSongCardIds(catalog, selectedSongIds);
    return (vocabulary || []).filter(card => cardIds.has(String(card.id)));
}

function isExampleObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) && (
        'spanish' in value || 'english' in value || 'translation_source' in value ||
        'song' in value || 'song_name' in value
    );
}

const DROP = Symbol('drop-song-example');

function filterExampleNode(value, selected) {
    if (Array.isArray(value)) {
        return value.map(child => filterExampleNode(child, selected)).filter(child => child !== DROP);
    }
    if (!value || typeof value !== 'object') return value;
    if (isExampleObject(value)) {
        const songId = value.song;
        if (songId !== undefined && songId !== null && songId !== '' && !selected.has(String(songId))) {
            return DROP;
        }
        return value;
    }
    return Object.fromEntries(Object.entries(value).map(([key, child]) => {
        const filtered = filterExampleNode(child, selected);
        return [key, filtered === DROP ? null : filtered];
    }));
}

export function filterExamplesForSongs(examples, catalog, selectedSongIds) {
    if (!catalog?.songs?.length || !examples) return examples;
    const selected = selectedSongIdSet(catalog, selectedSongIds);
    if (selected.size === catalog.songs.length) return examples;
    return filterExampleNode(examples, selected);
}
