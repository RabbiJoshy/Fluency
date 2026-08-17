export function selectedSongIdSet(catalog, selectedSongIds) {
    const available = new Set((catalog?.songs || []).map(song => String(song.id)));
    const selected = new Set((selectedSongIds || []).map(String).filter(id => available.has(id)));
    return (selected.size || catalog?.requireSelection) ? selected : available;
}

export function combineSongCatalogs(sources) {
    const bySongId = new Map();
    for (const source of sources || []) {
        const slug = String(source?.slug || source?.catalog?.source || '').trim();
        const catalog = source?.catalog;
        if (!slug || !Array.isArray(catalog?.songs)) continue;
        for (const song of catalog.songs) {
            const id = String(song?.id || '').trim();
            if (!id) continue;
            let combined = bySongId.get(id);
            if (!combined) {
                combined = {
                    id,
                    title: song.title || `Song ${id}`,
                    artist: song.artist || source.name || catalog.name || '',
                    spotifyTrackId: song.spotifyTrackId || '',
                    cardIds: [],
                    sourceKeys: []
                };
                bySongId.set(id, combined);
            }
            const sourceKey = `${slug}:${id}`;
            if (!combined.sourceKeys.includes(sourceKey)) combined.sourceKeys.push(sourceKey);
            combined.cardIds.push(...(song.cardIds || []).map(String));
            combined.cardIds = [...new Set(combined.cardIds)];
            if (!combined.artist && song.artist) combined.artist = song.artist;
            if (!combined.spotifyTrackId && song.spotifyTrackId) {
                combined.spotifyTrackId = song.spotifyTrackId;
            }
        }
    }
    const songs = Array.from(bySongId.values()).sort((a, b) =>
        String(a.artist).localeCompare(String(b.artist))
        || String(a.title).localeCompare(String(b.title))
        || String(a.id).localeCompare(String(b.id)));
    return {
        schemaVersion: 1,
        source: 'custom',
        name: 'Choose your own',
        songCount: songs.length,
        requireSelection: true,
        combinedSources: (sources || []).map(source => String(source?.slug || '')).filter(Boolean),
        songs
    };
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

function selectedSongSourceKeys(catalog, selected) {
    const keys = new Set();
    for (const song of catalog?.songs || []) {
        if (!selected.has(String(song.id))) continue;
        for (const sourceKey of song.sourceKeys || []) keys.add(String(sourceKey));
    }
    return keys;
}

function filterExampleNode(value, selected, sourceKeys, requireSourceMatch) {
    if (Array.isArray(value)) {
        return value
            .map(child => filterExampleNode(child, selected, sourceKeys, requireSourceMatch))
            .filter(child => child !== DROP);
    }
    if (!value || typeof value !== 'object') return value;
    if (isExampleObject(value)) {
        const songId = value.song;
        if (songId !== undefined && songId !== null && songId !== '') {
            if (requireSourceMatch) {
                const sourceKey = value.artist ? `${value.artist}:${songId}` : '';
                if (!sourceKey || !sourceKeys.has(sourceKey)) return DROP;
            } else if (!selected.has(String(songId))) {
                return DROP;
            }
        }
        return value;
    }
    return Object.fromEntries(Object.entries(value).map(([key, child]) => {
        const filtered = filterExampleNode(child, selected, sourceKeys, requireSourceMatch);
        return [key, filtered === DROP ? null : filtered];
    }));
}

export function filterExamplesForSongs(examples, catalog, selectedSongIds) {
    if (!catalog?.songs?.length || !examples) return examples;
    const selected = selectedSongIdSet(catalog, selectedSongIds);
    if (selected.size === catalog.songs.length) return examples;
    const requireSourceMatch = catalog.source === 'custom';
    return filterExampleNode(
        examples,
        selected,
        selectedSongSourceKeys(catalog, selected),
        requireSourceMatch
    );
}
