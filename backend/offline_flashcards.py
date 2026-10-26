"""Export a standalone, network-free HTML flashcard deck."""

import hashlib
import html
import json
import re

from backend.revision import clean_progress, flashcards


def offline_filename(topic):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(topic or "")).strip('_')[:60] or 'studystack'
    return slug + '_offline_flashcards.html'


def build_offline_flashcards(result):
    cards = [{"id": key, "front": str(card['front']), "back": str(card['back'])}
             for key, card in flashcards(result)]
    if not cards:
        raise ValueError('There are no flashcards to download.')
    identity = hashlib.sha256(json.dumps(sorted(card['id'] for card in cards)).encode()).hexdigest()[:24]
    payload = {"id": identity, "title": str(result.get('topic') or 'StudyStack flashcards'),
               "subject": str(result.get('subject') or ''), "cards": cards,
               "progress": clean_progress(result.get('review_progress'), result.get('flashcards', []))}
    encoded = json.dumps(payload, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    encoded = encoded.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    replacements = {'TITLE': html.escape(payload['title']), 'PAYLOAD': encoded, 'SCRIPT': SCRIPT}
    return re.sub(r'__(TITLE|PAYLOAD|SCRIPT)__', lambda match: replacements[match.group(1)], PAGE)


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'">
<title>__TITLE__ · Offline flashcards</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#edf0fc;color:#19203b;font-family:system-ui,sans-serif;line-height:1.5}main{max-width:780px;margin:36px auto;padding:0 18px}header{margin-bottom:24px}.brand{font-weight:800;color:#6750ce;font-size:14px;letter-spacing:.08em}h1{font-size:clamp(25px,5vw,38px);line-height:1.2;margin:12px 0}h2{font-size:14px;color:#626b89;font-weight:600}.card{border:1px solid #d7dcef;border-radius:24px;background:white;padding:30px;min-height:280px;box-shadow:0 14px 45px #313d7810}.body{font-size:clamp(21px,4vw,28px);white-space:pre-wrap;overflow-wrap:anywhere}.label{text-transform:uppercase;letter-spacing:.1em;font-size:12px;font-weight:700;color:#746d97}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0}button,.import{border:1px solid #c3c9e1;background:white;color:#343955;border-radius:12px;font:inherit;padding:11px 16px;cursor:pointer;min-height:44px}button.primary{background:#6550ce;color:white;border-color:#6550ce}button:disabled{opacity:.45;cursor:default}button:focus-visible,select:focus-visible,.import:focus-within{outline:3px solid #08a9cd;outline-offset:3px}.ratings button{flex:1 1 115px}.muted{font-size:13px;color:#626b89}.status{font-size:13px;font-weight:600;min-height:22px}.import input{max-width:220px;font:inherit}.footer{border-top:1px solid #d7dcef;margin-top:28px;padding-top:18px}select{font:inherit;padding:9px;border:1px solid #c3c9e1;border-radius:10px}progress{width:100%;height:9px;accent-color:#6550ce}.counter{margin-left:auto;font-weight:700}p{margin:10px 0}@media(max-width:480px){main{margin-top:20px}.card{padding:22px}.row button{flex:1}.counter{width:100%;margin-left:0}.import input{max-width:100%}}
</style></head><body><main>
<header><div class="brand">STUDYSTACK · OFFLINE</div><h1 id="title"></h1><p class="muted" id="subject"></p><p class="muted">This deck works without internet. No account or installation needed.</p></header>
<div class="row"><label>Show <select id="mode"><option value="all">All flashcards</option><option value="due">Due for revision</option></select></label><span class="counter" id="counter"></span></div>
<progress id="progress" max="1" value="0" aria-label="Cards reviewed"></progress><p class="muted" id="summary"></p>
<section class="card" aria-label="Flashcard"><h2 class="label" id="side">Question</h2><div class="body" id="content" dir="auto"></div></section>
<div class="row"><button id="prev">← Previous</button><button id="flip" class="primary">Show answer</button><button id="next">Next →</button></div>
<p class="muted">Try answering before revealing the answer. Then rate your recall:</p>
<div class="row ratings"><button id="again" disabled>Again</button><button id="hard" disabled>Hard</button><button id="good" disabled>Good</button><button id="easy" disabled>Easy</button></div>
<p class="status" id="status" role="status" aria-live="polite"></p>
<div class="footer"><p class="muted" id="storage"></p><div class="row"><button id="backup">Download progress backup</button><label class="import">Restore progress <input id="restore" type="file" accept="application/json,.json"></label></div>
<p class="muted">Offline progress stays on this device and does not automatically sync to your StudyStack account. Keep a backup before moving the file or clearing browser data.</p><p class="muted">Keyboard: Space to flip; ← / → to move. Formulas are shown as their saved text.</p></div>
<noscript>Enable JavaScript in your browser to study this offline deck.</noscript>
</main><script id="deck" type="application/json">__PAYLOAD__</script><script>__SCRIPT__</script></body></html>'''


SCRIPT = r'''
(() => {
  'use strict';
  const deck = JSON.parse(document.getElementById('deck').textContent);
  const byId = new Map(deck.cards.map(card => [card.id, card]));
  const get = id => document.getElementById(id);
  const ratings = ['Again', 'Hard', 'Good', 'Easy'];
  const storageKey = 'studystack-offline-v1-' + deck.id;
  let storageOK = true, index = 0, flipped = false, currentId = null;
  function clean(input) {
    const out = Object.create(null);
    if (!input || typeof input !== 'object' || Array.isArray(input)) return out;
    for (const id of byId.keys()) {
      const state = input[id];
      if (!state || typeof state !== 'object' || !ratings.includes(state.rating)) continue;
      const interval = Number(state.interval_days), reviews = Number(state.reviews);
      if (!Number.isFinite(interval) || !Number.isFinite(reviews) || !Number.isFinite(Date.parse(state.due_at))) continue;
      out[id] = {due_at: new Date(state.due_at).toISOString(),
        reviewed_at: Number.isFinite(Date.parse(state.reviewed_at)) ? new Date(state.reviewed_at).toISOString() : null,
        interval_days: Math.max(0, Math.min(365, interval)), reviews: Math.max(0, Math.min(100000, Math.trunc(reviews))), rating: state.rating};
    }
    return out;
  }
  let states = clean(deck.progress);
  
  function merge(input) {
    for (const [id, state] of Object.entries(clean(input))) {
      const previous = states[id];
      if (!previous || (Date.parse(state.reviewed_at) || 0) >= (Date.parse(previous.reviewed_at) || 0)) states[id] = state;
    }
  }
  try { merge(JSON.parse(localStorage.getItem(storageKey) || '{}')); }
  catch { storageOK = false; }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify(states)); storageOK = true; }
    catch { storageOK = false; }
    get('storage').textContent = storageOK
      ? 'Progress is saved in this browser when local-file storage is supported. Download a backup to keep a portable copy.'
      : 'This browser cannot save this file’s progress automatically. Download a progress backup before closing it.';
  }
  const isDue = card => !states[card.id] || Date.parse(states[card.id].due_at) <= Date.now();
  const cards = () => get('mode').value === 'due' ? deck.cards.filter(isDue).sort((a,b) =>
    (states[a.id] ? Date.parse(states[a.id].due_at) : Infinity) - (states[b.id] ? Date.parse(states[b.id].due_at) : Infinity)) : deck.cards;
    
  function nextState(previous, rating) {
    let interval = previous?.interval_days || 0;
    interval = rating === 'Again' ? 10 / 1440 : rating === 'Hard' ? Math.max(1, interval * 1.2)
      : rating === 'Good' ? Math.max(1, interval * 2.5) : Math.max(4, interval * 3.5);
    interval = Math.min(365, interval);
    return {interval_days: interval, reviews: Math.min(100000, (previous?.reviews || 0) + 1), rating,
      due_at: new Date(Date.now() + interval * 86400000).toISOString(), reviewed_at: new Date().toISOString()};
  }
  
  function label(state) {
    const days = state.interval_days;
    return days < 1 ? Math.max(1, Math.round(days * 1440)) + ' min' : Number(days.toFixed(1)) + (days === 1 ? ' day' : ' days');
  }
  
  function render() {
    const queue = cards(); index = Math.max(0, Math.min(index, queue.length - 1));
    const card = queue[index];
    if (currentId !== card?.id) flipped = false;
    currentId = card?.id || null;
    
    // If deck is completed
    if (get('side').textContent === 'Complete') {
        return;
    }

    get('counter').textContent = card ? `${index + 1} / ${queue.length}` : 'No cards due';
    get('side').textContent = card ? (flipped ? 'Answer' : 'Question') : 'Caught up';
    get('content').textContent = card ? (flipped ? card.back : card.front) : 'No cards are due right now. Come back later, or choose All flashcards.';
    get('flip').textContent = flipped ? 'Show question' : 'Show answer';
    for (const id of ['flip','prev','next']) get(id).disabled = !card;
    const due = deck.cards.filter(isDue).length;
    get('summary').textContent = `${Object.keys(states).length} of ${deck.cards.length} reviewed · ${due} due`;
    get('progress').value = Object.keys(states).length / deck.cards.length;
    for (const rating of ratings) {
      const button = get(rating.toLowerCase());
      button.disabled = !card || !flipped;
      button.textContent = rating + (card ? ' · ' + label(nextState(states[card.id], rating)) : '');
    }
  }
  
  function navigate(direction) { 
    const length = cards().length; 
    if (!length) return; 
    index = Math.max(0, Math.min(index + direction, length - 1)); 
    flipped = false; 
    render(); 
  }
  
  get('title').textContent = deck.title; get('subject').textContent = deck.subject;
  get('prev').onclick = () => navigate(-1); get('next').onclick = () => navigate(1);
  get('flip').onclick = () => { if (currentId) { flipped = !flipped; render(); } };
  get('mode').onchange = () => { index = 0; flipped = false; get('side').textContent = 'Question'; render(); };
  
  for (const rating of ratings) get(rating.toLowerCase()).onclick = () => {
    if (!currentId || !flipped) return;
    const state = nextState(states[currentId], rating); states[currentId] = state;
    persist(); get('status').textContent = `Recorded ${rating}. Next review in ${label(state)}.`;
    
    if (get('mode').value === 'all') {
      if (index < deck.cards.length - 1) {
        index++;
      } else {
        // Prevent loop, show finished state
        get('side').textContent = 'Complete';
        get('content').textContent = '🎉 You have reviewed all cards in this deck! Click Previous to go back.';
        get('flip').disabled = true;
        get('next').disabled = true;
        get('counter').textContent = `${deck.cards.length} / ${deck.cards.length}`;
        for (const r of ratings) get(r.toLowerCase()).disabled = true;
        get('status').textContent = 'Deck finished!';
        return;
      }
    }
    flipped = false; render();
  };
  
  get('backup').onclick = () => {
    const payload = {app:'studystack_offline_progress',version:1,deck_id:deck.id,progress:states};
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)], {type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'studystack_offline_progress.json';
    document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    get('status').textContent = 'Progress backup downloaded. Keep it with your offline deck.';
  };
  
  get('restore').onchange = async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('Progress backup is too large.');
      const value = JSON.parse(await file.text());
      if (value.app !== 'studystack_offline_progress' || value.version !== 1 || value.deck_id !== deck.id ||
          !value.progress || typeof value.progress !== 'object' || Array.isArray(value.progress)) throw new Error('Choose a progress backup from this exact flashcard deck.');
      merge(value.progress); persist(); flipped = false; render(); get('status').textContent = 'Progress restored. Newer reviews were kept.';
    } catch (error) { get('status').textContent = error.message || 'Could not restore progress.'; }
    event.target.value = '';
  };
  
  document.addEventListener('keydown', event => {
    if (['INPUT','SELECT','TEXTAREA','BUTTON'].includes(event.target.tagName) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.code === 'Space') { event.preventDefault(); get('flip').click(); }
    if (event.code === 'ArrowRight') { event.preventDefault(); navigate(1); }
    if (event.code === 'ArrowLeft') { event.preventDefault(); navigate(-1); }
  });
  
  persist(); render(); setInterval(render, 60000);
})();
'''
