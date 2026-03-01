import './state.js';

async function loadBadBunnyAlbumsDictionary() {
    try {
        const response = await fetch('Bad Bunny/bad_bunny_albums_dictionary.json');
        badBunnyAlbumsDictionary = await response.json();

        // Build reverse mapping: song name -> album image path
        for (const [albumKey, songs] of Object.entries(badBunnyAlbumsDictionary)) {
            const imagePath = albumToImagePath[albumKey] || defaultAlbumArt;
            for (const songName of songs) {
                // Store with lowercase for case-insensitive matching
                songToAlbumMap[songName.toLowerCase()] = imagePath;
            }
        }
        console.log('Bad Bunny albums dictionary loaded, mapped', Object.keys(songToAlbumMap).length, 'songs');
    } catch (error) {
        console.error('Failed to load Bad Bunny albums dictionary:', error);
    }
}

// Get album image for a song name
function getAlbumImageForSong(songName) {
    if (!songName) return defaultAlbumArt;
    // Try exact match first, then lowercase match
    return songToAlbumMap[songName] || songToAlbumMap[songName.toLowerCase()] || defaultAlbumArt;
}

// Function to update album artwork on card faces based on current example's song
function updateBadBunnyBackground() {
    if (!isBadBunnyMode) return;

    const cardFaces = document.querySelectorAll('.card-face');

    // Get current song name from the current example
    let songName = null;
    const card = flashcards[currentIndex];
    if (card && card.isMultiMeaning) {
        const currentMeaning = card.meanings[currentMeaningIndex];
        if (currentMeaning && currentMeaning.allExamples && currentMeaning.allExamples.length > 0) {
            const example = currentMeaning.allExamples[currentExampleIndex] || currentMeaning.allExamples[0];
            songName = example.song_name;
        }
    }

    const imageUrl = getAlbumImageForSong(songName);

    cardFaces.forEach(face => {
        face.style.backgroundImage = `url('${imageUrl}')`;
    });
}

window.loadBadBunnyAlbumsDictionary = loadBadBunnyAlbumsDictionary;
window.getAlbumImageForSong = getAlbumImageForSong;
window.updateBadBunnyBackground = updateBadBunnyBackground;
