import './state.js';

// Per-artist default album art, keyed by slug (for multi-artist fallback)
const artistDefaultArt = {};

async function loadArtistAlbumsDictionary() {
    if (!activeArtist || !activeArtist.albumsDictionary) return;
    try {
        const response = await fetch(activeArtist.albumsDictionary);
        artistAlbumsDictionary = await response.json();

        // Build reverse mapping: song name -> album image path
        const imageMap = activeArtist.albumImageMap || {};
        const fallback = activeArtist.defaultAlbumArt || '';
        for (const [albumKey, songs] of Object.entries(artistAlbumsDictionary)) {
            const imagePath = imageMap[albumKey] || fallback;
            for (const songName of songs) {
                songToAlbumMap[songName.toLowerCase()] = imagePath;
            }
        }
        console.log(`${activeArtist.name} albums dictionary loaded, mapped`, Object.keys(songToAlbumMap).length, 'songs');
    } catch (error) {
        console.error(`Failed to load ${activeArtist ? activeArtist.name : 'artist'} albums dictionary:`, error);
    }
}

// Get album image for a song name, using the example's artist slug for fallback
function getAlbumImageForSong(songName, artistSlug) {
    const fallback = (artistSlug && artistDefaultArt[artistSlug])
        || (activeArtist && activeArtist.defaultAlbumArt) || '';
    if (!songName) return fallback;
    return songToAlbumMap[songName] || songToAlbumMap[songName.toLowerCase()] || fallback;
}

// Update album artwork on card faces based on current example's song
function updateArtistBackground() {
    if (!activeArtist) return;

    const cardFaces = document.querySelectorAll('.card-face');

    let songName = null;
    let artistSlug = null;
    const card = flashcards[currentIndex];
    if (card && card.isMultiMeaning) {
        const currentMeaning = card.meanings[currentMeaningIndex];
        if (currentMeaning && currentMeaning.allExamples && currentMeaning.allExamples.length > 0) {
            const example = currentMeaning.allExamples[currentExampleIndex] || currentMeaning.allExamples[0];
            songName = example.song_name;
            artistSlug = example.artist;
        }
    }

    const imageUrl = getAlbumImageForSong(songName, artistSlug);

    cardFaces.forEach(face => {
        face.style.backgroundImage = imageUrl ? `url('${imageUrl}')` : '';
    });
}

// Load album dictionaries for multiple selected artists, merging song→image maps
async function loadMultiArtistAlbumsDictionaries(slugs, allConfigs) {
    songToAlbumMap = {}; // reset
    artistAlbumsDictionary = {};

    for (const slug of slugs) {
        const cfg = allConfigs[slug];
        if (!cfg || !cfg.albumsDictionary) continue;
        // Store per-artist default art for fallback
        artistDefaultArt[slug] = cfg.defaultAlbumArt || '';
        try {
            const response = await fetch(cfg.albumsDictionary);
            const dict = await response.json();
            const imageMap = cfg.albumImageMap || {};
            const fallback = cfg.defaultAlbumArt || '';
            for (const [albumKey, songs] of Object.entries(dict)) {
                const imagePath = imageMap[albumKey] || fallback;
                for (const songName of songs) {
                    songToAlbumMap[songName.toLowerCase()] = imagePath;
                }
            }
            // Merge into combined dictionary
            Object.assign(artistAlbumsDictionary, dict);
        } catch (error) {
            console.warn(`Failed to load albums for ${cfg.name}:`, error);
        }
    }
    console.log(`Multi-artist albums loaded, mapped ${Object.keys(songToAlbumMap).length} songs`);
}

window.loadArtistAlbumsDictionary = loadArtistAlbumsDictionary;
window.loadMultiArtistAlbumsDictionaries = loadMultiArtistAlbumsDictionaries;
window.getAlbumImageForSong = getAlbumImageForSong;
window.updateArtistBackground = updateArtistBackground;
