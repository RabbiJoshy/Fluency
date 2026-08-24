import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const source = await readFile(resolve(root, 'js/song-sets-core.js'), 'utf8');
const {
    combineSongCatalogs,
    filterExamplesForSongs,
    filterVocabularyForSongs,
    selectedSongCardIds,
    selectedSongIdSet
} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

const catalog = {
    songs: [
        { id: 'song-a', cardIds: ['a', 'shared'] },
        { id: 'song-b', cardIds: ['b', 'shared'] }
    ]
};

test('song membership filters cards without changing their IDs or order', () => {
    const cards = [{ id: 'shared' }, { id: 'b' }, { id: 'a' }];
    assert.deepEqual(filterVocabularyForSongs(cards, catalog, ['song-a']), [cards[0], cards[2]]);
    assert.deepEqual(Array.from(selectedSongCardIds(catalog, ['song-b'])).sort(), ['b', 'shared']);
    assert.deepEqual(Array.from(selectedSongIdSet(catalog, ['missing'])).sort(), ['song-a', 'song-b']);
});

test('examples keep dictionary evidence and only selected lyric songs', () => {
    const dictionary = { spanish: 'Hola.', english: 'Hello.', evidence: 'dictionary' };
    const a = { song: 'song-a', spanish: 'A' };
    const b = { song: 'song-b', spanish: 'B' };
    const examples = { card: { m: [[a, dictionary, b]], w: [[b]] } };
    assert.deepEqual(filterExamplesForSongs(examples, catalog, ['song-a']), {
        card: { m: [[a, dictionary]], w: [[]] }
    });
});

test('all songs is a no-copy fast path', () => {
    const cards = [{ id: 'a' }];
    const examples = { a: { m: [] } };
    assert.equal(filterVocabularyForSongs(cards, catalog, ['song-a', 'song-b']), cards);
    assert.equal(filterExamplesForSongs(examples, catalog, ['song-a', 'song-b']), examples);
});

test('custom catalog combines sources, deduplicates shared songs, and starts empty', () => {
    const custom = combineSongCatalogs([
        {
            slug: 'artist-a',
            name: 'Artist A',
            catalog: { songs: [{ id: 'shared-song', title: 'Together', cardIds: ['a'] }] }
        },
        {
            slug: 'artist-b',
            name: 'Artist B',
            catalog: {
                songs: [
                    { id: 'shared-song', title: 'Together', cardIds: ['b'] },
                    { id: 'solo-song', title: 'Solo', cardIds: ['solo'] }
                ]
            }
        }
    ]);
    assert.equal(custom.source, 'custom');
    assert.equal(custom.requireSelection, true);
    assert.equal(custom.songs.length, 2);
    assert.deepEqual(Array.from(selectedSongIdSet(custom, [])), []);
    const shared = custom.songs.find(song => song.id === 'shared-song');
    assert.deepEqual(shared.cardIds.sort(), ['a', 'b']);
    assert.deepEqual(shared.sourceKeys.sort(), ['artist-a:shared-song', 'artist-b:shared-song']);
});

test('custom examples require both the selected song and its real source', () => {
    const custom = {
        source: 'custom',
        requireSelection: true,
        songs: [
            { id: 'same-id', cardIds: ['a'], sourceKeys: ['artist-a:same-id'] },
            { id: 'other', cardIds: ['b'], sourceKeys: ['artist-b:other'] }
        ]
    };
    const dictionary = { spanish: 'Diccionario.', english: 'Dictionary.' };
    const selected = { artist: 'artist-a', song: 'same-id', spanish: 'A' };
    const falsePositive = { artist: 'artist-b', song: 'same-id', spanish: 'B' };
    const examples = { card: { m: [[selected, falsePositive, dictionary]] } };
    assert.deepEqual(filterExamplesForSongs(examples, custom, ['same-id']), {
        card: { m: [[selected, dictionary]] }
    });
    assert.deepEqual(filterVocabularyForSongs([{ id: 'a' }, { id: 'b' }], custom, []), []);
});

test('every configured Spanish song catalog has unique songs and valid deck card IDs', async () => {
    const artists = JSON.parse(await readFile(resolve(root, 'config/artists.json'), 'utf8'));
    const customSources = [];
    const uniqueSongIds = new Set();
    for (const [slug, config] of Object.entries(artists)) {
        if (!config.songsPath) continue;
        const catalogPath = resolve(root, config.songsPath);
        const songCatalog = JSON.parse(await readFile(catalogPath, 'utf8'));
        const index = JSON.parse(await readFile(resolve(root, config.indexPath), 'utf8'));
        const deckIds = new Set(index.map(card => String(card.id)));
        assert.equal(songCatalog.source, slug);
        if (config.language === 'spanish') {
            customSources.push({ slug, name: config.name, catalog: songCatalog });
            songCatalog.songs.forEach(song => uniqueSongIds.add(String(song.id)));
        }
        assert.equal(songCatalog.songCount, songCatalog.songs.length);
        assert.equal(new Set(songCatalog.songs.map(song => String(song.id))).size, songCatalog.songs.length);
        for (const song of songCatalog.songs) {
            assert.ok(song.id && song.title && song.cardIds.length, `${slug}: ${song.id}`);
            assert.ok(song.cardIds.every(cardId => deckIds.has(String(cardId))), `${slug}: ${song.title}`);
        }
    }
    assert.equal(artists['spanish-test-playlist'].name, 'Spanish Test Playlist');
    assert.equal(artists['spanish-test-playlist'].customSongSource, undefined);
    const custom = combineSongCatalogs(customSources);
    assert.equal(custom.songs.length, uniqueSongIds.size);
    assert.equal(new Set(custom.songs.map(song => song.id)).size, custom.songs.length);
    assert.ok(custom.songs.every(song => song.sourceKeys.length >= 1 && song.cardIds.length >= 1));
});

test('app stores the active song set, filters setup data, and resumes exact song IDs', async () => {
    const [module, main, ui, vocab, html, backend] = await Promise.all([
        readFile(resolve(root, 'js/song-sets.js'), 'utf8'),
        readFile(resolve(root, 'js/main.js'), 'utf8'),
        readFile(resolve(root, 'js/ui.js'), 'utf8'),
        readFile(resolve(root, 'js/vocab.js'), 'utf8'),
        readFile(resolve(root, 'index.html'), 'utf8'),
        readFile(resolve(root, 'backend/GoogleAppsScript.js'), 'utf8')
    ]);
    assert.match(module, /action: 'saveSongSet'/);
    assert.match(module, /action: 'loadSongSets'/);
    assert.match(module, /artistSlugsForSongs/);
    assert.match(module, /artistSlugs,/);
    assert.match(module, /song-set\|\$\{currentUser\.initials\}/);
    assert.match(main, /showSongSetPicker/);
    assert.match(main, /fluency-song-selection-changed/);
    assert.match(main, /invalidateLyricsSourceCaches/);
    assert.match(main, /await loadPpmData\(selectedLanguage\)/);
    assert.match(main, /CUSTOM_ARTIST_SLUG = 'custom'/);
    assert.match(main, /window\.showLyricsPicker = showLyricsPicker/);
    assert.doesNotMatch(main, /showLearningSourcePicker/);
    assert.match(ui, /window\.showLyricsPicker\?\.\(newLanguage, sourceCardButton\)/);
    assert.match(ui, /await continueToSpeech\(\)/);
    assert.doesNotMatch(ui, /learningSourceRadialPicker/);
    assert.match(ui, /window\.invalidateLyricsSourceCaches = invalidateLyricsSourceCaches/);
    assert.match(module, /combineSongCatalogs/);
    assert.match(module, /fluency_song_set_v1:/);
    assert.match(vocab, /songIds: activeArtist \? selectedSongIds\.slice\(\) : \[\]/);
    assert.match(vocab, /filterActiveSongVocabulary/);
    assert.match(vocab, /const masterByPath = new Map\(\)/);
    assert.match(vocab, /indexData = joinWithMaster\(indexData, sourceMaster\)/);
    assert.match(vocab, /existingMasterPath === sourceMasterPath/);
    assert.match(html, /id="songSetModal"/);
    assert.match(backend, /SONG_SETS_SHEET_NAME = 'SongSets'/);
    assert.match(backend, /SONG_SET_SCHEMA_VERSION = 2/);
    assert.match(backend, /'ArtistSlugsJson'/);
    assert.match(backend, /function saveSongSet/);
});
