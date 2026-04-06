import './state.js';

async function loadConfig() {
    try {
        const [configResponse, cefrResponse] = await Promise.all([
            fetch('config.json'),
            fetch('cefr_levels.json')
        ]);
        config = await configResponse.json();
        cefrLevelsConfig = await cefrResponse.json();

        // Override config for artist/lyrics mode
        if (activeArtist) {
            const lang = activeArtist.language || 'spanish';
            config.languages[lang] = {
                ...config.languages[lang],
                name: `${config.languages[lang].name} (${activeArtist.name})`,
                dataPath: activeArtist.dataPath,
                indexPath: activeArtist.indexPath || activeArtist.dataPath,
                examplesPath: activeArtist.examplesPath || null,
                masterPath: activeArtist.masterPath || null,
                ppmDataPath: null, // PPM data is embedded in artist vocabulary JSON
                colorTheme: activeArtist.colorTheme || config.languages[lang].colorTheme
            };
            percentageMode = true;
            document.title = `${activeArtist.name} Vocabulary`;
        }
    } catch (error) {
        console.error('Failed to load config:', error);
        alert('Failed to load configuration. Please refresh the page.');
    }
}

// Get the CEFR levels for the language (always use standard, not lemma-specific ranges)
function getCefrLevels(language) {
    if (cefrLevelsConfig && cefrLevelsConfig[language]) {
        // Always use standard levels - lemma mode just filters cards within the same ranges
        return cefrLevelsConfig[language].standard;
    }
    // Fallback to config.json levels
    return config.languages[language].cefrLevels;
}

// Load PPM data for percentage mode
async function loadPpmData(language) {
    const langConfig = config.languages[language];

    // First try to load from ppmDataPath (CSV file)
    if (langConfig && langConfig.ppmDataPath) {
        try {
            const response = await fetch(langConfig.ppmDataPath);
            if (response.ok) {
                const csvText = await response.text();
                const lines = csvText.replace(/\r/g, '').trim().split('\n');
                const headers = lines[0].split(',');
                const ppmIndex = headers.indexOf('occurrences_ppm');
                const rankIndex = headers.indexOf('rank');

                if (ppmIndex !== -1) {
                    ppmData = [];
                    totalPpm = 0;

                    for (let i = 1; i < lines.length; i++) {
                        const values = lines[i].split(',');
                        const ppm = parseFloat(values[ppmIndex]) || 0;
                        const rank = parseInt(values[rankIndex]) || i;
                        ppmData.push({ rank, ppm });
                    }

                    recalculateCumulativePercents();
                    return true;
                }
            }
        } catch (error) {
            console.log('CSV PPM load failed, trying JSON fallback:', error);
        }
    }

    // Fallback: try to load from vocabulary JSON if it has corpus_count or occurrences_ppm embedded
    const vocabJsonPath = langConfig.indexPath || langConfig.dataPath;
    if (langConfig && vocabJsonPath && vocabJsonPath.endsWith('.json')) {
        try {
            const response = await fetch(vocabJsonPath);
            if (response.ok) {
                const vocabData = await response.json();
                // Check if vocab has corpus_count (preferred) or occurrences_ppm (legacy)
                const hasCorpusCount = vocabData.length > 0 && vocabData[0].hasOwnProperty('corpus_count');
                const hasOccPpm = vocabData.length > 0 && vocabData[0].hasOwnProperty('occurrences_ppm');
                if (hasCorpusCount || hasOccPpm) {
                    ppmData = [];
                    totalPpm = 0;

                    // Vocab JSON is pre-sorted by the pipeline; use array index as rank
                    for (let idx = 0; idx < vocabData.length; idx++) {
                        const item = vocabData[idx];
                        const freq = hasCorpusCount ? (item.corpus_count || 0) : (item.occurrences_ppm || 0);
                        ppmData.push({ rank: idx + 1, ppm: freq, id: item.id });
                    }

                    recalculateCumulativePercents();
                    console.log('Loaded frequency data from vocabulary JSON:', ppmData.length, 'entries');
                    return true;
                }
            }
        } catch (error) {
            console.error('Failed to load frequency data from vocabulary JSON:', error);
        }
    }

    ppmData = null;
    totalPpm = 0;
    return false;
}

// Recalculate cumulative percentages on ppmData.
// When hideSingleOccurrence is ON, the denominator excludes freq-1 words
// so coverage percentages reflect only multi-occurrence vocabulary.
function recalculateCumulativePercents() {
    if (!ppmData || ppmData.length === 0) return;

    totalPpm = 0;
    for (let i = 0; i < ppmData.length; i++) {
        if (hideSingleOccurrence && ppmData[i].ppm <= 1) continue;
        totalPpm += ppmData[i].ppm;
    }

    let cumulative = 0;
    for (let i = 0; i < ppmData.length; i++) {
        if (hideSingleOccurrence && ppmData[i].ppm <= 1) {
            // Excluded words carry no coverage — leave cumulativePercent at
            // whatever the previous real word reached (don't advance it).
            ppmData[i].cumulativePercent = totalPpm > 0 ? cumulative / totalPpm : 0;
        } else {
            cumulative += ppmData[i].ppm;
            ppmData[i].cumulativePercent = totalPpm > 0 ? cumulative / totalPpm : 0;
        }
    }
}

// Get percentage-based level ranges
function getPercentageLevelRanges() {
    if (!ppmData || ppmData.length === 0) return [];

    // When hiding single-occurrence words, cap at the last multi-occurrence rank
    let maxRank = ppmData.length;
    if (hideSingleOccurrence) {
        for (let i = ppmData.length - 1; i >= 0; i--) {
            if (ppmData[i].ppm > 1) {
                maxRank = ppmData[i].rank;
                break;
            }
        }
    }

    const ranges = [];
    let prevRank = 0;

    for (const level of percentageLevels) {
        // Find the rank where cumulative percentage reaches this threshold
        let endRank = maxRank;
        for (let i = 0; i < ppmData.length; i++) {
            if (ppmData[i].rank > maxRank) break;
            // Skip single-occurrence words — they carry cumulativePercent=1.0
            // which would otherwise match every threshold prematurely.
            if (hideSingleOccurrence && ppmData[i].ppm <= 1) continue;
            if (ppmData[i].cumulativePercent >= level.threshold) {
                endRank = ppmData[i].rank;
                break;
            }
        }

        // Cap endRank at maxRank
        endRank = Math.min(endRank, maxRank);

        // Only add this level if it has any range
        if (endRank > prevRank) {
            ranges.push({
                level: level.level,
                description: level.description,
                startRank: prevRank + 1,
                endRank: endRank,
                threshold: level.threshold
            });
        }

        prevRank = endRank;
    }

    return ranges;
}

// Calculate cumulative coverage based on correct words

window.loadConfig = loadConfig;
window.getCefrLevels = getCefrLevels;
window.loadPpmData = loadPpmData;
window.recalculateCumulativePercents = recalculateCumulativePercents;
window.getPercentageLevelRanges = getPercentageLevelRanges;
