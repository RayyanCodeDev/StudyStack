"""Browser speech controls for existing Streamlit content (no voice API key)."""

import html
import re

import streamlit as st

try:
    import streamlit.components.v2 as components
except ImportError:
    components = None


def speech_text(value):
    """Remove common Markdown/LaTeX notation without changing the displayed notes."""
    text = str(value or "")
    text = re.sub(r"```[^\n]*\n([\s\S]*?)```", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r" \1 divided by \2 ", text)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r" square root of \1 ", text)
    for command, spoken in {"times": " times ", "cdot": " times ", "leq": " less than or equal to ",
                            "geq": " greater than or equal to ", "neq": " not equal to ",
                            "rightarrow": " leads to ", "approx": " approximately "}.items():
        text = re.sub(r"\\" + command + r"\b", spoken, text)
    text = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\([A-Za-z]+)", r" \1 ", text)
    text = re.sub(r"\^\{?([\w+-]+)\}?", r" to the power of \1 ", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|>\s*)", "", text)
    text = re.sub(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", "", text)
    text = re.sub(r"[*_`$|{}]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def concept_map_text(topic, concepts, links):
    names = list(dict.fromkeys(str(c).strip() for c in concepts if str(c).strip()))
    canonical = {name.casefold(): name for name in names}
    parts = [f"Concept map. Topic: {topic}.", "Concepts: " + "; ".join(names) + "."]
    seen = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        a = canonical.get(str(link.get("from", "")).strip().casefold())
        b = canonical.get(str(link.get("to", "")).strip().casefold())
        pair = tuple(sorted((a, b))) if a and b else None
        if a and b and a != b and pair not in seen:
            seen.add(pair)
            parts.append(f"{a} is linked to {b}.")
    return "\n".join(parts)


def quiz_reading_text(question, checked=False, correct=False):
    parts = ["Question: " + str(question.get("q", ""))]
    parts.extend(f"Option {i + 1}: {option}." for i, option in enumerate(question.get("options", [])))
    if checked:
        parts.append("Your answer was correct." if correct else "Your answer was not correct.")
        parts.append("The correct answer is: " + str(question.get("answer", "")))
    return "\n".join(parts)


HTML = """
<div class="reader" role="group" aria-label="Read aloud controls">
  <div class="controls">
    <button type="button" data-action="all">🔊 Read aloud</button>
    <button type="button" data-action="selected" disabled>Read selected</button>
    <button type="button" data-action="pause" disabled>Pause</button>
    <button type="button" data-action="stop" disabled>Stop</button>
  </div>
  <div class="settings">
    <label>Voice <select data-setting="voice" aria-label="Reading voice"><option value="">Device default</option></select></label>
    <label>Speed <select data-setting="speed" aria-label="Reading speed"><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option></select></label>
  </div>
  <p class="hint">Highlight an extract in this section, then choose Read selected.</p>
  <p class="status" role="status" aria-live="polite">Ready.</p>
</div>
"""

CSS = """
.reader{font-family:inherit;color:var(--text,var(--st-text-color,#20263a));border:1px solid var(--border,#939bb466);border-radius:16px;padding:12px;margin:4px 0 10px;background:var(--glass,transparent)}
.controls,.settings{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.settings{margin-top:10px}
button,select{font:inherit;font-size:14px;border-radius:10px;padding:8px 12px;border:1px solid #7c8cff77;min-height:38px}
button{background:#6550d8;color:white;cursor:pointer}button:hover:not(:disabled){background:#503dc0}button:disabled{opacity:.48;cursor:default}
select{background:var(--st-secondary-background-color,#f1f2f7);color:var(--st-text-color,#20263a);max-width:100%}
label{display:flex;align-items:center;gap:6px;font-size:13px}.hint,.status{font-size:12px;margin:8px 0 0;line-height:1.5}.status{font-weight:600}
button:focus-visible,select:focus-visible{outline:3px solid #00bce5;outline-offset:2px}
@media(max-width:520px){.controls button{flex:1 1 40%}.settings label{width:100%}.settings select{flex:1;min-width:0}}
"""

JS = r"""
export default function(component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector('.reader');
  const get = (name) => root.querySelector(`[data-action="${name}"]`);
  const all = get('all'), selected = get('selected'), pause = get('pause'), stop = get('stop');
  const voicesMenu = root.querySelector('[data-setting="voice"]');
  const speedMenu = root.querySelector('[data-setting="speed"]');
  const status = root.querySelector('.status');
  const hint = root.querySelector('.hint');
  const scope = document.querySelector('.st-key-' + data.scope);
  const owner = Symbol('studystack-reader');
  const bus = window.__studyStackSpeech || (window.__studyStackSpeech = { owner: null });
  const synth = window.speechSynthesis;
  let extracted = '', active = false, paused = false, generation = 0, utterance = null;
  let queue = [], position = 0, selectedVoice = null, speed = 1, disposed = false;
  const supported = !!synth && typeof window.SpeechSynthesisUtterance === 'function';
  const visible = () => !!scope && scope.isConnected && scope.getClientRects().length > 0 && root.getClientRects().length > 0;
  const belongs = (node) => node instanceof Node && !!scope && scope.contains(node);
  const inToolbar = (node) => !!node && (root.contains(node) || node.getRootNode?.() === parentElement);
  const text = (value) => String(value || '').replace(/\s+/g, ' ').trim();

  function setStatus(message) { if (!disposed) status.textContent = message; }
  function buttons() {
    all.disabled = !supported || !text(data.text);
    selected.disabled = !supported || !extracted;
    pause.disabled = !active;
    stop.disabled = !active;
    pause.textContent = paused ? 'Resume' : 'Pause';
  }
  function clearSelection() { extracted = ''; hint.textContent = 'Highlight an extract in this section, then choose Read selected.'; buttons(); }
  function captureSelection() {
    if (!visible()) return;
    const field = document.activeElement;
    if (belongs(field) && (field.tagName === 'TEXTAREA' || field.tagName === 'INPUT') && field.type !== 'password') {
      const value = text(field.value.slice(field.selectionStart || 0, field.selectionEnd || 0));
      if (value) extracted = value;
    } else {
      const choice = document.getSelection();
      if (!choice || choice.rangeCount === 0) return;
      const range = choice.getRangeAt(0);
      const value = text(choice.toString());
      if (value && belongs(range.startContainer) && belongs(range.endContainer) &&
          !inToolbar(range.startContainer) && !inToolbar(range.endContainer)) {
        extracted = value;
      } else if (value && !inToolbar(range.startContainer)) {
        clearSelection(); return;
      }
    }
    if (extracted) hint.textContent = `Selected extract: ${extracted.length} characters. Choose Read selected.`;
    buttons();
  }
  function pointerDown(event) {
    const path = event.composedPath();
    if (path.includes(root)) return;
    if (!path.some(node => node === scope || belongs(node))) clearSelection();
    else if (event.detail > 0) clearSelection();
  }
  // Speech engines can stall on very long utterances; keep every chunk bounded.
  function chunks(value) {
    const input = text(value);
    const out = [];
    let remaining = input;
    while (remaining.length > 220) {
      let cut = -1;
      for (const match of remaining.slice(0, 220).matchAll(/[.!?۔؟;:]\s/g)) if (match.index >= 60) cut = match.index + 1;
      if (cut < 0) cut = remaining.lastIndexOf(' ', 220);
      if (cut < 1) cut = 220;
      out.push(remaining.slice(0, cut).trim());
      remaining = remaining.slice(cut).trim();
    }
    if (remaining) out.push(remaining);
    return out;
  }
  function finish(message, cancel = false) {
    generation += 1;
    active = false; paused = false; queue = []; position = 0;
    if (bus.owner === owner) {
      bus.owner = null;
      if (cancel && supported) synth.cancel();
    }
    utterance = null;
    buttons(); setStatus(message);
  }
  function speakNext(token) {
    if (disposed || token !== generation || !active || bus.owner !== owner) return;
    if (position >= queue.length) { finish('Finished reading.'); return; }
    utterance = new SpeechSynthesisUtterance(queue[position]);
    if (selectedVoice) { utterance.voice = selectedVoice; utterance.lang = selectedVoice.lang; }
    else utterance.lang = /[\u0600-\u06ff]/.test(queue[position]) ? 'ur-PK' : 'en-GB';
    utterance.rate = speed;
    utterance.onend = () => {
      if (token !== generation || disposed) return;
      position += 1;
      if (!paused) speakNext(token);
    };
    utterance.onerror = (event) => {
      if (token !== generation || disposed) return;
      if (event.error === 'canceled' || event.error === 'interrupted') finish('Reading stopped.');
      else finish('Could not play this voice. Try another voice, check your device sound, and press Read aloud again.', true);
    };
    setStatus(`Reading part ${position + 1} of ${queue.length}.`);
    try { synth.speak(utterance); }
    catch { finish('Speech could not start. Try another installed voice or browser.', true); }
  }
  function start(value) {
    if (!supported) return;
    const parts = chunks(value);
    if (!parts.length) { setStatus('Select some text to read first.'); return; }
    window.dispatchEvent(new CustomEvent('studystack-reader-start', { detail: owner }));
    finish('Ready.', true);
    synth.cancel();
    synth.resume();
    bus.owner = owner;
    queue = parts; position = 0; active = true; paused = false;
    selectedVoice = synth.getVoices().find(voice => voice.voiceURI === voicesMenu.value) || null;
    speed = Number(speedMenu.value) || 1;
    buttons();
    // Called directly from the user's click, preserving browser user activation.
    speakNext(generation);
  }
  function populateVoices() {
    if (!supported) return;
    const before = voicesMenu.value;
    voicesMenu.replaceChildren();
    voicesMenu.add(new Option('Device default', ''));
    synth.getVoices().forEach(voice => voicesMenu.add(new Option(`${voice.name} (${voice.lang})`, voice.voiceURI)));
    if ([...voicesMenu.options].some(option => option.value === before)) voicesMenu.value = before;
  }
  function otherReader(event) { if (event.detail !== owner && active) finish('Another section is reading.', true); }
  function checkVisibility() { if (active && !visible()) finish('Reading stopped: section closed.', true); }
  all.onclick = () => start(data.text);
  selected.onclick = () => { captureSelection(); if (extracted) start(extracted); };
  pause.onclick = () => {
    if (!active || bus.owner !== owner) return;
    paused = !paused;
    if (paused) { synth.pause(); setStatus('Paused.'); }
    else { synth.resume(); if (!synth.speaking && position < queue.length) speakNext(generation); setStatus('Reading resumed.'); }
    buttons();
  };
  stop.onclick = () => finish('Reading stopped.', true);
  // Preserve a highlighted extract when the mouse focuses a control.
  root.querySelectorAll('button').forEach(button => button.addEventListener('mousedown', event => event.preventDefault()));
  document.addEventListener('selectionchange', captureSelection);
  document.addEventListener('select', captureSelection, true);
  document.addEventListener('pointerdown', pointerDown, true);
  window.addEventListener('studystack-reader-start', otherReader);
  if (supported) synth.addEventListener('voiceschanged', populateVoices);
  const observer = new MutationObserver(checkVisibility);
  for (let node = root; node && node !== document.body; node = node.parentElement || node.getRootNode()?.host || null) {
    observer.observe(node, { attributes: true, attributeFilter: ['hidden', 'aria-hidden', 'style', 'class', 'open'] });
  }
  populateVoices(); buttons();
  if (!supported) setStatus('Read aloud is unavailable in this browser. Try a browser with text-to-speech support.');
  else setStatus('Ready. Voices depend on your device.');
  return () => {
    finish('Reading stopped.', true); disposed = true;
    observer.disconnect();
    document.removeEventListener('selectionchange', captureSelection);
    document.removeEventListener('select', captureSelection, true);
    document.removeEventListener('pointerdown', pointerDown, true);
    window.removeEventListener('studystack-reader-start', otherReader);
    if (supported) synth.removeEventListener('voiceschanged', populateVoices);
  };
}
"""

_reader = components.component("studystack_read_aloud", html=HTML, css=CSS, js=JS) if components else None


def read_aloud(value, *, key, scope):
    """Mount controls beside a keyed Streamlit container's study content."""
    if _reader is None:
        st.caption("Read aloud needs the updated requirements.txt (Streamlit 1.56 or newer).")
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]+", scope):
        raise ValueError("Reader scope must be a simple container key.")
    # Untrusted notes go through component data, never HTML or JavaScript templates.
    _reader(key=key, data={"text": speech_text(value), "scope": scope})
