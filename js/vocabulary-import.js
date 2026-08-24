import './state.js?v=20260824a';
import { sendOrQueue } from './sync-queue.js?v=20260824a';
import {
    buildImportBulkChunks,
    buildVocabularyImportPlan,
    importPlanFingerprint,
    parseVocabularyImport
} from './vocabulary-import-core.js?v=20260824a';

let currentPlan = null;
let previewAccount = '';

function element(id) {
    return document.getElementById(id);
}

function setStatus(message, error = false) {
    const status = element('vocabularyImportStatus');
    status.textContent = message || '';
    status.classList.toggle('is-error', error);
}

function clearPreview() {
    currentPlan = null;
    previewAccount = '';
    element('vocabularyImportPreview').hidden = true;
    element('confirmVocabularyImportBtn').disabled = true;
}

function openVocabularyImportModal() {
    if (!currentUser || currentUser.isGuest) return;
    element('settingsModal')?.classList.add('hidden');
    element('vocabularyImportModal').classList.remove('hidden');
    setStatus('');
    clearPreview();
    element('vocabularyImportText').focus();
}

function closeVocabularyImportModal({ reopenSettings = true } = {}) {
    element('vocabularyImportModal').classList.add('hidden');
    clearPreview();
    if (reopenSettings) window.showSettingsModalWithTab?.('account');
}

function summaryCell(value, label) {
    const cell = document.createElement('div');
    const number = document.createElement('strong');
    const description = document.createElement('span');
    number.textContent = String(value);
    description.textContent = label;
    cell.append(number, description);
    return cell;
}

function renderSkipped(plan) {
    const details = element('vocabularyImportSkipped');
    const lines = [];
    for (const row of plan.invalid) {
        lines.push(`Line ${row.line}: ${row.surface || '(blank)'} — ${row.reason}`);
    }
    for (const row of plan.unmatched) {
        lines.push(`Unmatched: ${row.surface}`);
    }
    for (const row of plan.ambiguous) {
        lines.push(`Not imported (ambiguous or invalid card ID): ${row.surface}`);
    }
    details.hidden = lines.length === 0;
    details.open = false;
    element('vocabularyImportSkippedText').textContent = lines.join('\n');
}

function renderPreview(plan) {
    let known = 0;
    let review = 0;
    let due = 0;
    for (const entry of plan.entries) {
        const state = window.getProgressState?.(entry.progress) || {};
        if (state.isDue) due++;
        else if (state.needsReview) review++;
        else known++;
    }

    const summary = element('vocabularyImportSummary');
    summary.replaceChildren(
        summaryCell(plan.inputRows, 'Input rows'),
        summaryCell(plan.matchedCount, 'Matched cards'),
        summaryCell(plan.duplicateCount, 'Duplicates collapsed'),
        summaryCell(plan.changedEntries.length, 'Cards to update'),
        summaryCell(plan.existingCount, 'Already tracked'),
        summaryCell(plan.changedExistingCount, 'Tracked cards updated'),
        summaryCell(plan.invalid.length + plan.unmatched.length + plan.ambiguous.length, 'Skipped'),
        summaryCell(known, 'Known after import'),
        summaryCell(review, 'Review after import'),
        summaryCell(due, 'Due after import')
    );
    renderSkipped(plan);
    element('vocabularyImportPreview').hidden = false;
    element('confirmVocabularyImportBtn').disabled = plan.changedEntries.length === 0;
    if (!plan.matchedCount) {
        setStatus('No rows matched an exact Spanish Speech surface.', true);
    } else if (!plan.changedEntries.length) {
        setStatus(`${plan.matchedCount} matched card${plan.matchedCount === 1 ? ' is' : 's are'} already up to date.`);
    } else {
        setStatus(`Ready to update ${plan.changedEntries.length} card${plan.changedEntries.length === 1 ? '' : 's'}. Review the preview, then confirm.`);
    }
}

async function previewVocabularyImport() {
    clearPreview();
    if (!currentUser || currentUser.isGuest) {
        setStatus('Sign in with a named account before importing progress.', true);
        return;
    }
    const text = element('vocabularyImportText').value;
    setStatus('Matching exact surfaces against Spanish Speech…');
    element('previewVocabularyImportBtn').disabled = true;
    try {
        const parsed = parseVocabularyImport(text);
        const normalConfig = window._normalModeLangConfigs?.spanish;
        if (!normalConfig) throw new Error('Spanish Speech configuration is not ready yet.');
        const vocabulary = await window.fetchAndJoinIndex(normalConfig);
        currentPlan = buildVocabularyImportPlan(parsed, vocabulary, progressData, { now: Date.now() });
        previewAccount = currentUser.initials;
        renderPreview(currentPlan);
    } catch (error) {
        clearPreview();
        setStatus(error?.message || 'The vocabulary list could not be read.', true);
    } finally {
        element('previewVocabularyImportBtn').disabled = false;
    }
}

async function confirmVocabularyImport() {
    if (!currentPlan || !currentPlan.changedEntries.length) return;
    if (!currentUser || currentUser.isGuest || currentUser.initials !== previewAccount) {
        clearPreview();
        setStatus('The signed-in account changed. Preview the import again.', true);
        return;
    }
    const button = element('confirmVocabularyImportBtn');
    button.disabled = true;
    setStatus('Saving on this device and queueing account sync…');
    try {
        const fingerprint = importPlanFingerprint(currentPlan);
        const chunks = buildImportBulkChunks(currentPlan, currentUser.initials);
        for (let index = 0; index < chunks.length; index++) {
            await sendOrQueue({
                action: 'bulkSave',
                sheet: 'Progress',
                rows: chunks[index]
            }, `vocabulary-import|${currentUser.initials}|${fingerprint}|${index}`);
        }
        for (const entry of currentPlan.changedEntries) {
            progressData[entry.itemId] = { ...entry.progress };
        }
        window.cacheProgressLocally?.({ immediate: true });
        window.updateIncorrectButtonVisibility?.();
        window.updateTotalStatsButtonVisibility?.();
        await window.refreshSetupAfterProgress?.();
        const count = currentPlan.changedEntries.length;
        currentPlan = null;
        previewAccount = '';
        setStatus(`${count} Spanish Speech card${count === 1 ? '' : 's'} saved on this device and queued to sync.`);
        element('confirmVocabularyImportBtn').disabled = true;
    } catch (error) {
        button.disabled = false;
        setStatus(error?.message || 'The import could not be queued. Nothing has been sent directly.', true);
    }
}

function setupVocabularyImport() {
    const open = element('openVocabularyImportBtn');
    const modal = element('vocabularyImportModal');
    if (!open || !modal || modal.dataset.listenersReady === '1') return;
    modal.dataset.listenersReady = '1';
    open.addEventListener('click', openVocabularyImportModal);
    element('closeVocabularyImportModal').addEventListener('click', () => closeVocabularyImportModal());
    modal.addEventListener('click', event => {
        if (event.target === modal) closeVocabularyImportModal();
    });
    element('previewVocabularyImportBtn').addEventListener('click', previewVocabularyImport);
    element('confirmVocabularyImportBtn').addEventListener('click', confirmVocabularyImport);
    element('vocabularyImportText').addEventListener('input', () => {
        if (currentPlan) {
            clearPreview();
            setStatus('The list changed. Preview it again before importing.');
        }
    });
    element('vocabularyImportFile').addEventListener('change', async event => {
        const file = event.target.files?.[0];
        if (!file) return;
        clearPreview();
        try {
            element('vocabularyImportText').value = await file.text();
            setStatus(`${file.name} loaded. Preview it before importing.`);
        } catch (_) {
            setStatus('The selected file could not be read.', true);
        } finally {
            event.target.value = '';
        }
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeVocabularyImportModal();
        }
    });
}

setupVocabularyImport();

window.openVocabularyImportModal = openVocabularyImportModal;
