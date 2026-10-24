/*
 * Minimale Laufzeit für den NFL-Tracker auf GitHub Pages.
 *
 * Die Seite wurde als Dashboard-Artifact gebaut und spricht eine kleine
 * `dash`-API an (data, onData, calc, setLink ...). Dieses Skript stellt genau
 * diese API bereit, liest die Daten aber aus data/*.json statt aus dem Artifact-Speicher.
 * An der Seite selbst muss dadurch nichts umgeschrieben werden.
 */
(function () {
  'use strict';

  var FILES = ['games', 'standings', 'boxscores'];
  var files = {};   // id -> {status, data}
  var calcs = {};   // id -> {inputs, fn, out}
  var subs = [];
  var ready = false;

  function columnsOf(rows) {
    return Array.isArray(rows) && rows.length && typeof rows[0] === 'object' && rows[0] !== null
      ? Object.keys(rows[0]) : [];
  }

  function result(status, data) {
    return { status: status, data: data, rows: data, columns: columnsOf(data), message: '', refreshing: false, meta: [] };
  }

  function data(id) {
    var c = calcs[id];
    if (c) {
      var ins = c.inputs.map(data);
      var bad = ins.filter(function (i) { return i.status !== 'ok'; });
      if (bad.length) return result(bad.some(function (i) { return i.status === 'error'; }) ? 'error' : 'loading', []);
      if (!c.out) {
        try { c.out = c.fn.apply(null, ins.map(function (i) { return i.data; })); }
        catch (e) { console.error('calc ' + id + ' fehlgeschlagen', e); return result('error', []); }
      }
      return result('ok', c.out);
    }
    var f = files[id];
    return f ? result(f.status, f.data) : result('missing', []);
  }

  function notify() {
    subs.forEach(function (fn) {
      try { fn(); } catch (e) { console.error(e); }
    });
  }

  function fetchJson(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error(url + ': HTTP ' + r.status);
      return r.json();
    });
  }

  function fillMeta(meta) {
    var src = document.getElementById('nf-source');
    var upd = document.getElementById('nf-updated');
    if (src && meta.source) src.textContent = meta.source;
    if (upd && meta.updated_at) {
      var d = new Date(meta.updated_at);
      if (!isNaN(d)) {
        upd.textContent = new Intl.DateTimeFormat('de-DE', {
          timeZone: 'Europe/Berlin', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'
        }).format(d) + ' Uhr';
      }
    }
  }

  window.dash = {
    data: data,
    onData: function (fn) {
      subs.push(fn);
      if (ready) { try { fn(); } catch (e) { console.error(e); } }
    },
    calc: function (id, def) { calcs[id] = { inputs: def.inputs, fn: def.fn, out: null }; },
    loader: function () {},
    setLink: function (name) { try { history.replaceState(null, '', '#' + name); } catch (e) {} },
    params: function () { return {}; },
    setParams: function () {},
    resetParams: function () {},
    refresh: function () { return load(); },
    colors: ['#2f9e6b', '#f26a21', '#c2284f', '#4f8cff', '#e0b43a', '#9b6bff', '#2bb3c0', '#8b98a9']
  };

  function load() {
    var jobs = FILES.map(function (id) {
      files[id] = files[id] || { status: 'loading', data: [] };
      return fetchJson('data/' + id + '.json').then(
        function (rows) { files[id] = { status: 'ok', data: rows }; },
        function (err) { console.error(err); files[id] = { status: 'error', data: [] }; }
      );
    });
    jobs.push(fetchJson('data/meta.json').then(fillMeta, function () {}));
    return Promise.all(jobs).then(function () {
      Object.keys(calcs).forEach(function (k) { calcs[k].out = null; });
      ready = true;
      notify();
    });
  }

  // Diagramme werden aus der Breite des Containers gezeichnet, also bei Größenänderung neu.
  var timer = null;
  var lastWidth = 0;
  window.addEventListener('resize', function () {
    if (!ready) return;
    var w = document.documentElement.clientWidth;
    if (w === lastWidth) return;
    lastWidth = w;
    clearTimeout(timer);
    timer = setTimeout(notify, 120);
  });

  document.addEventListener('DOMContentLoaded', function () { lastWidth = document.documentElement.clientWidth; load(); });
})();
