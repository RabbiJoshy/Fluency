import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const root = resolve(import.meta.dirname, '..');

test('Spotify playback identity includes the requested example timestamp', async () => {
    const spotify = await readFile(resolve(root, 'js/spotify.js'), 'utf8');
    const helpers = spotify.slice(
        spotify.indexOf('function _normalizedSpotifyPosition'),
        spotify.indexOf('async function spotifyPlayTrack')
    );
    const context = {};
    runInNewContext(`${helpers}; result = {
        sameExample: (() => {
            _currentTrackId = 'track-a';
            _currentTrackStartMs = 12000;
            return _isCurrentPlaybackRequest('track-a', 12000);
        })(),
        sameSongDifferentExample: _isCurrentPlaybackRequest('track-a', 47000),
        differentSongSameTimestamp: _isCurrentPlaybackRequest('track-b', 12000),
        normalizedTimestamp: _normalizedSpotifyPosition('47000')
    };`, context);

    assert.equal(context.result.sameExample, true);
    assert.equal(context.result.sameSongDifferentExample, false);
    assert.equal(context.result.differentSongSameTimestamp, false);
    assert.equal(context.result.normalizedTimestamp, 47000);
    assert.match(
        spotify,
        /if \(_isCurrentPlaybackRequest\(trackId, positionMs\) && !options\.forceStart\)/
    );
});
