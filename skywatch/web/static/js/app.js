(function() {
    'use strict';

    // ── Public API (initialized early so all code can attach to it) ──
    window.skywatch = {};

    // ── State ──
    let targets = [];
    let aprsStations = [];
    let aprsMessages = [];
    let markers = {};
    let aprsMarkers = {};
    let selectedId = null;
    let activeFilter = 'all';
    let ws = null;

    // ── Map styles ──
    var MAP_STYLES = {
        'dark': {
            name: 'Dark',
            url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
            attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            filter: 'brightness(0.7) contrast(1.1) saturate(0.8)'
        },
        'light': {
            name: 'Light',
            url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
            attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            filter: 'none'
        },
        'satellite': {
            name: 'Satellite',
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attribution: '&copy; Esri',
            subdomains: '',
            filter: 'none'
        },
        'topo': {
            name: 'Topo',
            url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
            subdomains: 'abc',
            filter: 'none'
        },
        'streets': {
            name: 'Streets',
            url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>',
            subdomains: 'abc',
            filter: 'none'
        },
        'dark-matter': {
            name: 'Dark Matter',
            url: 'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png',
            attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            filter: 'none'
        }
    };
    var currentStyle = localStorage.getItem('skywatch-map-style') || 'dark';
    var TILE_URL = MAP_STYLES[currentStyle].url;
    var currentTileLayer = null;

    // ── Offline tile cache (IndexedDB) ──
    var tileDB = null;

    function openTileDB() {
        return new Promise(function(resolve, reject) {
            var req = indexedDB.open('skywatch-tiles', 1);
            req.onupgradeneeded = function(e) {
                e.target.result.createObjectStore('tiles');
            };
            req.onsuccess = function(e) { tileDB = e.target.result; resolve(tileDB); };
            req.onerror = function() { resolve(null); };
        });
    }

    function getTile(key) {
        if (!tileDB) return Promise.resolve(null);
        return new Promise(function(resolve) {
            var tx = tileDB.transaction('tiles', 'readonly');
            var req = tx.objectStore('tiles').get(key);
            req.onsuccess = function() { resolve(req.result || null); };
            req.onerror = function() { resolve(null); };
        });
    }

    function putTile(key, blob) {
        if (!tileDB) return Promise.resolve();
        return new Promise(function(resolve) {
            var tx = tileDB.transaction('tiles', 'readwrite');
            tx.objectStore('tiles').put(blob, key);
            tx.oncomplete = function() { resolve(); };
            tx.onerror = function() { resolve(); };
        });
    }

    function countCachedTiles() {
        if (!tileDB) return Promise.resolve(0);
        return new Promise(function(resolve) {
            var tx = tileDB.transaction('tiles', 'readonly');
            var req = tx.objectStore('tiles').count();
            req.onsuccess = function() { resolve(req.result); };
            req.onerror = function() { resolve(0); };
        });
    }

    function clearTileCache() {
        if (!tileDB) return Promise.resolve();
        return new Promise(function(resolve) {
            var tx = tileDB.transaction('tiles', 'readwrite');
            tx.objectStore('tiles').clear();
            tx.oncomplete = function() { resolve(); };
            tx.onerror = function() { resolve(); };
        });
    }

    // Cache-first tile layer: serves from IndexedDB if available, falls back to network
    L.TileLayer.Offline = L.TileLayer.extend({
        createTile: function(coords, done) {
            var tile = document.createElement('img');
            tile.crossOrigin = 'anonymous';
            var url = this.getTileUrl(coords);
            var key = currentStyle + '/' + coords.z + '/' + coords.x + '/' + coords.y;

            getTile(key).then(function(blob) {
                if (blob) {
                    tile.src = URL.createObjectURL(blob);
                    done(null, tile);
                } else {
                    tile.onload = function() {
                        // Cache the tile for offline use
                        fetch(url).then(function(r) { return r.blob(); }).then(function(b) {
                            putTile(key, b);
                        }).catch(function() {});
                        done(null, tile);
                    };
                    tile.onerror = function() { done(new Error('Tile load failed'), tile); };
                    tile.src = url;
                }
            }).catch(function() {
                tile.onload = function() { done(null, tile); };
                tile.onerror = function() { done(new Error('Tile load failed'), tile); };
                tile.src = url;
            });

            return tile;
        }
    });

    // ── Map setup ──
    // Restore last view from localStorage so the user doesn\'t have to
    // re-zoom every session.
    var _savedView = null;
    try {
        _savedView = JSON.parse(localStorage.getItem('skywatch.map.view') || 'null');
    } catch (e) { _savedView = null; }
    var map = L.map('map', {
        center: (_savedView && _savedView.lat != null) ? [_savedView.lat, _savedView.lon] : [39.8283, -98.5795],
        zoom: (_savedView && _savedView.zoom != null) ? _savedView.zoom : 5,
        zoomControl: true,
    });
    map.on('moveend zoomend', function() {
        var c = map.getCenter();
        try {
            localStorage.setItem('skywatch.map.view',
                JSON.stringify({ lat: c.lat, lon: c.lng, zoom: map.getZoom() }));
        } catch (e) {}
    });

    function applyMapStyle(styleId) {
        var style = MAP_STYLES[styleId];
        if (!style) return;
        currentStyle = styleId;
        TILE_URL = style.url;
        localStorage.setItem('skywatch-map-style', styleId);

        if (currentTileLayer) map.removeLayer(currentTileLayer);

        var opts = {
            attribution: style.attribution,
            maxZoom: 19,
        };
        if (style.subdomains) opts.subdomains = style.subdomains;

        currentTileLayer = new L.TileLayer.Offline(style.url, opts).addTo(map);

        // Apply CSS filter for dark themes
        var pane = document.querySelector('.leaflet-tile-pane');
        if (pane) pane.style.filter = style.filter || 'none';

        // Update active button
        var btns = document.querySelectorAll('.map-style-btn');
        btns.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-style') === styleId);
        });
    }

    openTileDB().then(function() {
        applyMapStyle(currentStyle);
    });

    // ── Icons ──
    // Categorize vessel by AIS ship type code into icon + color
    // SVG ship silhouettes — all point "up" (bow at top), 24x24 viewBox.
    // Designed to be recognizable at small sizes.
    var VESSEL_SVGS = {
        // Long, narrow, straight hull — typical bulk carrier / container ship
        cargo: '<polygon points="12,2 8,8 8,21 16,21 16,8" stroke-width="0.8"/><rect x="9" y="11" width="6" height="2" fill="rgba(0,0,0,0.3)" stroke="none"/><rect x="9" y="14" width="6" height="2" fill="rgba(0,0,0,0.3)" stroke="none"/><rect x="9" y="17" width="6" height="2" fill="rgba(0,0,0,0.3)" stroke="none"/>',
        // Long with rounded bow, distinct cargo deck markings
        tanker: '<path d="M 12 2 Q 7 6 7 10 L 7 21 L 17 21 L 17 10 Q 17 6 12 2 Z" stroke-width="0.8"/><circle cx="10" cy="13" r="1" fill="rgba(0,0,0,0.4)" stroke="none"/><circle cx="14" cy="13" r="1" fill="rgba(0,0,0,0.4)" stroke="none"/><circle cx="10" cy="17" r="1" fill="rgba(0,0,0,0.4)" stroke="none"/><circle cx="14" cy="17" r="1" fill="rgba(0,0,0,0.4)" stroke="none"/>',
        // Tall, elegant cruise/passenger ship with multiple decks
        passenger: '<path d="M 12 2 Q 8 5 8 9 L 8 18 L 6 21 L 18 21 L 16 18 L 16 9 Q 16 5 12 2 Z" stroke-width="0.8"/><line x1="9" y1="11" x2="15" y2="11" stroke-width="0.5"/><line x1="9" y1="13" x2="15" y2="13" stroke-width="0.5"/><line x1="9" y1="15" x2="15" y2="15" stroke-width="0.5"/>',
        // Triangular sail above small hull
        sailing: '<path d="M 12 3 L 12 16 L 17 14 Z" stroke-width="0.8"/><line x1="12" y1="3" x2="12" y2="20" stroke-width="0.7"/><path d="M 7 18 L 17 18 L 15 21 L 9 21 Z" stroke-width="0.8"/>',
        // Sleek, pointed speedboat
        speedboat: '<path d="M 12 3 L 8 10 L 8 18 Q 12 21 16 18 L 16 10 Z" stroke-width="0.8"/><line x1="10" y1="14" x2="14" y2="14" stroke-width="0.6"/>',
        // Compact, chunky tug with raised wheelhouse
        tug: '<path d="M 12 4 L 9 8 L 9 20 L 15 20 L 15 8 Z" stroke-width="0.8"/><rect x="10" y="9" width="4" height="4" fill="rgba(0,0,0,0.35)" stroke="none"/><circle cx="12" cy="6" r="1" fill="currentColor" stroke="none"/>',
        // Small fishing boat with characteristic blunt bow
        fishing: '<path d="M 12 5 L 9 9 L 9 19 Q 12 21 15 19 L 15 9 Z" stroke-width="0.7"/><line x1="12" y1="5" x2="12" y2="2" stroke-width="0.6"/><line x1="11" y1="3" x2="13" y2="3" stroke-width="0.6"/>',
        // Coast Guard / law enforcement — sleek with a stripe
        patrol: '<path d="M 12 2 L 8 9 L 8 20 L 16 20 L 16 9 Z" stroke-width="0.8"/><line x1="8" y1="13" x2="16" y2="13" stroke-width="1.5" stroke="rgba(255,255,255,0.7)"/>',
        // Military — long, angular warship silhouette
        military: '<path d="M 12 2 L 9 7 L 8 11 L 8 19 L 16 19 L 16 11 L 15 7 Z" stroke-width="0.8"/><rect x="11" y="9" width="2" height="3" fill="rgba(0,0,0,0.5)" stroke="none"/><line x1="12" y1="3" x2="12" y2="9" stroke-width="0.5"/>',
        // Pilot vessel - small with tall mast
        pilot: '<path d="M 12 5 L 9 9 L 9 19 L 15 19 L 15 9 Z" stroke-width="0.8"/><line x1="12" y1="2" x2="12" y2="9" stroke-width="0.7"/><circle cx="12" cy="11" r="1" fill="currentColor" stroke="none"/>',
        // Generic vessel — anchor-like
        vessel: '<circle cx="12" cy="12" r="6" stroke-width="1.2" fill="rgba(0,0,0,0.2)"/><path d="M 12 8 L 12 16 M 9 12 L 15 12" stroke-width="1.5"/>',
    };

    function vesselCategory(shipType) {
        var c = shipType || 0;
        if (c === 30) return { svg: VESSEL_SVGS.fishing, color: '#94a3b8', name: 'fishing' };
        if (c === 31 || c === 32 || c === 52) return { svg: VESSEL_SVGS.tug, color: '#fbbf24', name: 'tug' };
        if (c === 33) return { svg: VESSEL_SVGS.tug, color: '#f97316', name: 'dredging' };
        if (c === 35) return { svg: VESSEL_SVGS.military, color: '#ef4444', name: 'military' };
        if (c === 36) return { svg: VESSEL_SVGS.sailing, color: '#a78bfa', name: 'sailing' };
        if (c === 37) return { svg: VESSEL_SVGS.speedboat, color: '#34d399', name: 'pleasure' };
        if (c >= 40 && c <= 49) return { svg: VESSEL_SVGS.speedboat, color: '#06b6d4', name: 'highspeed' };
        if (c === 50) return { svg: VESSEL_SVGS.pilot, color: '#fbbf24', name: 'pilot' };
        if (c === 51) return { svg: VESSEL_SVGS.patrol, color: '#ef4444', name: 'sar' };
        if (c === 53) return { svg: VESSEL_SVGS.tug, color: '#fbbf24', name: 'tender' };
        if (c === 54) return { svg: VESSEL_SVGS.vessel, color: '#34d399', name: 'antipoll' };
        if (c === 55) return { svg: VESSEL_SVGS.patrol, color: '#3b82f6', name: 'lawenf' };
        if (c === 58) return { svg: VESSEL_SVGS.patrol, color: '#ef4444', name: 'medical' };
        if (c >= 60 && c <= 69) return { svg: VESSEL_SVGS.passenger, color: '#a78bfa', name: 'passenger' };
        if (c >= 70 && c <= 79) return { svg: VESSEL_SVGS.cargo, color: '#34d399', name: 'cargo' };
        if (c >= 80 && c <= 89) return { svg: VESSEL_SVGS.tanker, color: '#f97316', name: 'tanker' };
        return { svg: VESSEL_SVGS.vessel, color: '#34d399', name: 'vessel' };
    }

    function vesselIcon(heading, target) {
        var cat = vesselCategory(target ? target.ship_type : 0);
        var rot = heading || 0;
        var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" ' +
            'style="transform:rotate(' + rot + 'deg);filter:drop-shadow(0 0 2px rgba(0,0,0,0.8));" ' +
            'fill="' + cat.color + '" stroke="' + cat.color + '" stroke-linejoin="round" stroke-linecap="round">' +
            cat.svg + '</svg>';
        return L.divIcon({
            html: svg,
            className: 'vessel-icon-wrap',
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });
    }

    // Sidebar list shows a smaller version of the same SVG
    function vesselSidebarIcon(target) {
        var cat = vesselCategory(target ? target.ship_type : 0);
        return '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" ' +
            'fill="' + cat.color + '" stroke="' + cat.color + '" stroke-linejoin="round" stroke-linecap="round">' +
            cat.svg + '</svg>';
    }

    function aircraftIcon(heading, category) {
        var isMil = category === 'military' || category === 'mil-helo';
        var isHelo = category === 'helicopter' || category === 'mil-helo';
        var color = isMil ? '#ef4444' : '#38bdf8';
        // Helicopter: 🚁 (U+1F681), Aircraft: ✈ (U+2708)
        var symbol = isHelo ? '&#x1F681;' : '&#9992;';
        var size = isHelo ? 20 : 22;
        return L.divIcon({
            html: '<div style="transform:rotate(' + (isHelo ? 0 : (heading || 0)) + 'deg);font-size:' + size + 'px;color:' + color + ';text-shadow:0 0 4px rgba(0,0,0,0.8);">' + symbol + '</div>',
            className: '',
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });
    }

    const icons = {
        aircraft: function(heading, category) {
            return aircraftIcon(heading, category);
        },
        vessel: function(heading, target) {
            return vesselIcon(heading, target);
        },
        drone: function(heading) {
            return L.divIcon({
                html: `<div class="marker-drone" style="font-size:16px;">&#x2B23;</div>`,
                className: '',
                iconSize: [18, 18],
                iconAnchor: [9, 9],
            });
        },
    };

    // ── WebSocket ──
    function connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws`);

        ws.onopen = function() {
            document.getElementById('connection-status').className = 'badge connected';
            document.getElementById('connection-status').textContent = 'Connected';
        };

        ws.onclose = function() {
            document.getElementById('connection-status').className = 'badge disconnected';
            document.getElementById('connection-status').textContent = 'Disconnected';
            setTimeout(connect, 2000);
        };

        ws.onmessage = function(evt) {
            try {
                var data = JSON.parse(evt.data);
                targets = data.targets || [];
                aprsStations = data.aprs || [];
                aprsMessages = data.messages || [];
                if (data.alert_zones) handleAlertZonesPayload(data.alert_zones);
                if (data.alert_events) handleAlertEventsPayload(data.alert_events);
                updateAll();
                if (activeFilter === 'aprs') updateAPRSMessages();
            } catch(e) {
                console.error('Parse error:', e);
            }
        };
    }

    // ── Update everything ──
    function updateAll() {
        updateStats();
        updateMap();
        updateAPRSMap();
        if (activeFilter === 'noaa') {
            renderNOAAPanel();
        } else {
            updateList();
        }
        if (selectedId) updateDetail();
    }

    function updateStats() {
        let ac = 0, vs = 0, dr = 0;
        targets.forEach(function(t) {
            if (t.type === 'aircraft') ac++;
            else if (t.type === 'vessel') vs++;
            else if (t.type === 'drone') dr++;
        });
        document.getElementById('aircraft-count').textContent = 'Aircraft: ' + ac;
        document.getElementById('vessel-count').textContent = 'Vessels: ' + vs;
        document.getElementById('drone-count').textContent = 'Drones: ' + dr;
        var visibleAPRS = aprsStations.filter(function(s) {
            if (s.lat === 0 && s.lon === 0) return false;
            return map.getBounds().contains([s.lat, s.lon]);
        });
        document.getElementById('aprs-count').textContent = 'APRS: ' + visibleAPRS.length;
    }

    function updateMap() {
        const activeIds = new Set();

        targets.forEach(function(t) {
            if (t.lat === 0 && t.lon === 0) return;
            activeIds.add(t.id);

            const iconFn = icons[t.type];
            if (!iconFn) return;

            var icon;
            if (t.type === 'aircraft') {
                icon = iconFn(t.heading, t.category);
            } else if (t.type === 'vessel') {
                icon = iconFn(t.heading, t);
            } else {
                icon = iconFn(t.heading);
            }

            if (markers[t.id]) {
                markers[t.id].setLatLng([t.lat, t.lon]);
                markers[t.id].setIcon(icon);
            } else {
                const m = L.marker([t.lat, t.lon], { icon: icon })
                    .addTo(map)
                    .on('click', function() { selectTarget(t.id); });
                markers[t.id] = m;
            }

            // Tooltip
            const label = t.callsign || t.ship_name || t.drone_id || t.id;
            markers[t.id].bindTooltip(label, {
                permanent: false,
                direction: 'top',
                className: 'leaflet-tooltip',
            });
        });

        // Remove stale markers
        Object.keys(markers).forEach(function(id) {
            if (!activeIds.has(id)) {
                map.removeLayer(markers[id]);
                delete markers[id];
            }
        });
    }

    function updateList() {
        const list = document.getElementById('target-list');
        let html = '';

        // Regular targets (aircraft, vessels, drones)
        if (activeFilter !== 'aprs') {
            const filtered = targets.filter(function(t) {
                return activeFilter === 'all' || t.type === activeFilter;
            }).sort(function(a, b) {
                return (b.messages || 0) - (a.messages || 0);
            });

            filtered.forEach(function(t) {
                var name = t.callsign || t.ship_name || t.drone_id || t.id;
                // For aircraft, show registration + type if available
                var subline = '';
                if (t.type === 'aircraft') {
                    var parts = [];
                    if (t.registration) parts.push(t.registration);
                    if (t.aircraft_type) parts.push(t.aircraft_type);
                    else if (t.typecode) parts.push(t.typecode);
                    if (parts.length > 0) subline = parts.join(' — ');
                } else if (t.type === 'vessel') {
                    var parts = [];
                    if (t.ship_type_str) parts.push(t.ship_type_str);
                    if (t.country) parts.push(t.country);
                    if (t.length) parts.push(Math.round(t.length) + 'm');
                    if (parts.length > 0) subline = parts.join(' — ');
                }
                var meta = buildMeta(t);
                var isMil = t.category === 'military' || t.category === 'mil-helo';
                var isHelo = t.category === 'helicopter' || t.category === 'mil-helo';
                var icon, iconColor = '';
                if (t.type === 'aircraft') {
                    icon = isHelo ? '&#x1F681;' : '&#9992;';
                    if (isMil) iconColor = 'color:#ef4444;';
                } else if (t.type === 'vessel') {
                    icon = vesselSidebarIcon(t);
                    iconColor = '';
                } else {
                    icon = '&#x2B23;';
                }
                var nameClass = t.type + (isMil ? ' military' : '');
                var sel = t.id === selectedId ? ' selected' : '';
                var catBadge = '';
                if (isMil) catBadge = '<span class="cat-badge mil">MIL</span> ';
                else if (isHelo) catBadge = '<span class="cat-badge helo">HELO</span> ';
                html += '<div class="target-item' + sel + '" data-id="' + t.id + '" onclick="window.skywatch.select(\'' + t.id + '\')">' +
                    '<div class="target-icon" style="' + iconColor + '">' + icon + '</div>' +
                    '<div class="target-info">' +
                        '<div class="target-name ' + nameClass + '">' + catBadge + escHtml(name) + '</div>' +
                        (subline ? '<div class="target-subline">' + escHtml(subline) + '</div>' : '') +
                        '<div class="target-meta">' + escHtml(meta) + '</div>' +
                    '</div>' +
                '</div>';
            });
        }

        // APRS stations — only show on the APRS tab
        if (activeFilter === 'aprs') {
            var mapBounds = map.getBounds();
            const sorted = aprsStations.filter(function(s) {
                if (s.lat === 0 && s.lon === 0) return false;
                return mapBounds.contains([s.lat, s.lon]);
            }).sort(function(a, b) {
                return (b.messages || 0) - (a.messages || 0);
            });

            sorted.forEach(function(s) {
                const srcClass = s.source.toLowerCase().replace('-', '');
                const sel = selectedId === 'aprs-' + s.callsign ? ' selected' : '';
                const meta = buildAPRSMeta(s);
                const symIcon = aprsSymbolHTML(s.symbol, 24);
                html += `<div class="target-item${sel}" onclick="window.skywatch.select('aprs-${escHtml(s.callsign)}')">
                    <div class="target-icon">${symIcon}</div>
                    <div class="target-info">
                        <div class="target-name aprs-${srcClass}">
                            <span class="aprs-source-badge ${srcClass}">${escHtml(s.source)}</span>
                            ${escHtml(s.callsign)}
                        </div>
                        <div class="target-meta">${escHtml(meta)}</div>
                        ${s.last_packet ? '<div class="packet-raw">' + escHtml(s.last_packet) + '</div>' : ''}
                    </div>
                </div>`;
            });
        }

        list.innerHTML = html;
    }

    function buildAPRSMeta(s) {
        var parts = [];
        if (s.comment) parts.push(s.comment);
        if (s.speed) parts.push(s.speed.toFixed(1) + ' kts');
        if (s.course) parts.push(s.course + '\u00B0');
        if (s.altitude) parts.push(s.altitude + ' ft');
        if (s.messages) parts.push(s.messages + ' msgs');
        return parts.join(' \u00B7 ');
    }

    function buildMeta(t) {
        const parts = [];
        if (t.type === 'aircraft') {
            if (t.altitude) parts.push(Math.round(t.altitude) + ' ft');
            if (t.speed) parts.push(Math.round(t.speed) + ' kts');
            if (t.squawk) parts.push('SQ ' + t.squawk);
        } else if (t.type === 'vessel') {
            if (t.speed) parts.push(t.speed.toFixed(1) + ' kts');
            if (t.nav_status) parts.push(t.nav_status);
            if (t.destination) parts.push('→ ' + t.destination);
        } else if (t.type === 'drone') {
            if (t.altitude) parts.push(Math.round(t.altitude) + ' m');
            if (t.operator) parts.push('Op: ' + t.operator);
        }
        if (t.messages) parts.push(t.messages + ' msgs');
        return parts.join(' · ');
    }

    function selectTarget(id) {
        selectedId = id;
        updateDetail();
        updateList();

        // APRS stations still use the side detail panel.
        if (id && id.startsWith('aprs-')) {
            var call = id.substring(5);
            var s = aprsStations.find(function(x) { return x.callsign === call; });
            if (s && s.lat && s.lon) map.panTo([s.lat, s.lon]);
            return;
        }

        // Aircraft / vessels / drones get a popup anchored to the marker.
        const t = targets.find(function(x) { return x.id === id; });
        if (!t || !t.lat || !t.lon) return;
        map.panTo([t.lat, t.lon]);
        var marker = markers[id];
        if (marker) {
            marker.bindPopup(buildTargetPopupHTML(t), {
                maxWidth: 320, minWidth: 240, autoPan: true,
                className: 'target-popup',
            }).openPopup();
            marker.once('popupclose', function() {
                if (selectedId === id) {
                    selectedId = null;
                    updateList();
                }
            });
        }
    }

    // Cache vessel photos so we don't re-fetch on every WS update.
    var vesselPhotoCache = {};

    function buildTargetDetailRows(t) {
        var rows = [];
        rows.push(detailRow('Type', t.type.charAt(0).toUpperCase() + t.type.slice(1)));
        rows.push(detailRow('ID', t.id));
        if (t.callsign) rows.push(detailRow('Callsign', t.callsign));
        if (t.registration) rows.push(detailRow('Registration', t.registration));
        if (t.aircraft_type) rows.push(detailRow('Aircraft', t.aircraft_type));
        if (t.typecode) rows.push(detailRow('Type Code', t.typecode));
        if (t.operator) rows.push(detailRow('Operator', t.operator));
        if (t.owner) rows.push(detailRow('Owner', t.owner));
        if (t.lat || t.lon) rows.push(detailRow('Position', t.lat.toFixed(5) + ', ' + t.lon.toFixed(5)));
        if (t.altitude) rows.push(detailRow('Altitude', Math.round(t.altitude) + (t.type === 'aircraft' ? ' ft' : ' m')));
        if (t.speed) rows.push(detailRow('Speed', t.speed.toFixed(1) + ' kts'));
        if (t.heading) rows.push(detailRow('Heading', Math.round(t.heading) + '°'));
        if (t.squawk) rows.push(detailRow('Squawk', t.squawk));
        if (t.mmsi) rows.push(detailRow('MMSI', t.mmsi));
        if (t.ship_name) rows.push(detailRow('Ship Name', t.ship_name));
        if (t.imo) rows.push(detailRow('IMO', t.imo));
        if (t.ship_type_str) rows.push(detailRow('Vessel Type', t.ship_type_str));
        if (t.country) rows.push(detailRow('Flag', t.country));
        if (t.nav_status) rows.push(detailRow('Status', t.nav_status));
        if (t.destination) rows.push(detailRow('Destination', t.destination));
        if (t.eta) rows.push(detailRow('ETA', t.eta));
        if (t.length) rows.push(detailRow('Length', t.length + ' m'));
        if (t.beam) rows.push(detailRow('Beam', t.beam + ' m'));
        if (t.draught) rows.push(detailRow('Draught', t.draught.toFixed(1) + ' m'));
        if (t.drone_id) rows.push(detailRow('Drone ID', t.drone_id));
        if (t.messages) rows.push(detailRow('Messages', t.messages));
        if (t.last_seen) rows.push(detailRow('Last Seen', new Date(t.last_seen).toLocaleTimeString()));

        if (t.type === 'vessel' && t.mmsi) {
            var mmsiNum = t.mmsi.replace(/^0+/, '');
            var vlinks = [
                '<a href="https://www.marinetraffic.com/en/ais/details/ships/mmsi:' + mmsiNum + '" target="_blank" rel="noopener" class="ext-link">MarineTraffic</a>',
                '<a href="https://www.vesselfinder.com/vessels?name=&mmsi=' + mmsiNum + '" target="_blank" rel="noopener" class="ext-link">VesselFinder</a>',
                '<a href="https://www.myshiptracking.com/vessels/mmsi-' + mmsiNum + '" target="_blank" rel="noopener" class="ext-link">MyShipTracking</a>',
            ];
            if (t.imo) vlinks.push('<a href="https://www.marinetraffic.com/en/ais/details/ships/imo:' + t.imo + '" target="_blank" rel="noopener" class="ext-link">By IMO</a>');
            rows.push('<div class="detail-row ext-links-row"><span class="detail-label">More Info</span><span class="detail-value">' + vlinks.join(' · ') + '</span></div>');
        }
        if (t.type === 'aircraft' && t.id && t.id.indexOf('ICAO-') === 0) {
            var hex = t.id.substring(5);
            var alinks = [
                '<a href="https://globe.adsbexchange.com/?icao=' + hex + '" target="_blank" rel="noopener" class="ext-link">ADSBexchange</a>',
                '<a href="https://flightaware.com/live/modes/' + hex + '/redirect" target="_blank" rel="noopener" class="ext-link">FlightAware</a>',
                '<a href="https://www.flightradar24.com/data/aircraft/' + (t.registration || hex).toLowerCase() + '" target="_blank" rel="noopener" class="ext-link">FlightRadar24</a>',
            ];
            if (t.registration) alinks.push('<a href="https://www.jetphotos.com/photo/keyword/' + t.registration + '" target="_blank" rel="noopener" class="ext-link">JetPhotos</a>');
            rows.push('<div class="detail-row ext-links-row"><span class="detail-label">More Info</span><span class="detail-value">' + alinks.join(' · ') + '</span></div>');
        }
        return rows;
    }

    function buildTargetPopupHTML(t) {
        var title = t.callsign || t.ship_name || t.drone_id || t.id;
        var header = '<div class="target-popup-header" style="font-weight:600;color:#e0e6ed;border-bottom:1px solid #1e293b;padding-bottom:6px;margin-bottom:6px">' +
            escHtml(title) + ' <span style="color:#64748b;font-weight:400;font-size:11px">' + escHtml(t.type) + '</span></div>';
        var photoBlock = '';
        if (t.type === 'vessel' && t.ship_name) {
            var cached = vesselPhotoCache[t.ship_name];
            if (cached && cached.thumbnail) {
                photoBlock =
                    '<a href="' + cached.page_url + '" target="_blank" rel="noopener">' +
                    '<img src="' + cached.thumbnail + '" alt="' + escHtml(cached.title || t.ship_name) + '" ' +
                    'style="max-width:100%;border-radius:6px;display:block;margin:0 0 6px"/></a>' +
                    (cached.description ? '<div style="font-size:11px;color:#94a3b8;margin-bottom:6px">' + escHtml(cached.description) + '</div>' : '');
            } else if (cached === undefined) {
                vesselPhotoCache[t.ship_name] = null;
                fetch('/api/vessel/photo?name=' + encodeURIComponent(t.ship_name))
                    .then(function(r) { return r.json(); })
                    .then(function(p) {
                        vesselPhotoCache[t.ship_name] = p || null;
                        var m = markers[t.id];
                        var current = targets.find(function(x) { return x.id === t.id; });
                        if (m && current && m.isPopupOpen && m.isPopupOpen()) {
                            m.setPopupContent(buildTargetPopupHTML(current));
                        }
                    })
                    .catch(function() {});
            }
        }
        return '<div class="target-popup-body" style="font-size:12px;color:#cbd5e1;max-height:320px;overflow-y:auto">' +
            header + photoBlock + buildTargetDetailRows(t).join('') + '</div>';
    }

    function updateDetail() {
        const panel = document.getElementById('detail-panel');
        const content = document.getElementById('detail-content');

        // Aircraft / vessel / drone detail now lives in a map popup anchored
        // to the marker. The side panel is reserved for APRS stations.
        if (!selectedId || !selectedId.startsWith('aprs-')) {
            panel.classList.add('hidden');
            if (selectedId) {
                var t = targets.find(function(x) { return x.id === selectedId; });
                var m = markers[selectedId];
                if (t && m && m.isPopupOpen && m.isPopupOpen()) {
                    m.setPopupContent(buildTargetPopupHTML(t));
                }
            }
            return;
        }

        var call = selectedId.substring(5);
        var s = aprsStations.find(function(x) { return x.callsign === call; });
        if (!s) { panel.classList.add('hidden'); return; }

        panel.classList.remove('hidden');
        var rows = [];
        rows.push(detailRow('Callsign', s.callsign));
        rows.push(detailRow('Source', s.source));
        if (s.lat || s.lon) rows.push(detailRow('Position', s.lat.toFixed(5) + ', ' + s.lon.toFixed(5)));
        if (s.symbol) rows.push(detailRow('Symbol', s.symbol));
        if (s.speed) rows.push(detailRow('Speed', s.speed.toFixed(1) + ' kts'));
        if (s.course) rows.push(detailRow('Course', s.course + '°'));
        if (s.altitude) rows.push(detailRow('Altitude', s.altitude + ' ft'));
        if (s.comment) rows.push(detailRow('Comment', s.comment));
        if (s.messages) rows.push(detailRow('Messages', s.messages));
        if (s.last_packet) rows.push(detailRow('Last Packet', s.last_packet));
        if (s.seen) rows.push(detailRow('Last Seen', new Date(s.seen * 1000).toLocaleTimeString()));
        content.innerHTML = rows.join('');
    }

    function detailRow(label, value) {
        return `<div class="detail-row"><span class="detail-label">${label}</span><span class="detail-value">${escHtml(String(value))}</span></div>`;
    }

    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Filter buttons ──
    document.querySelectorAll('.filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            activeFilter = btn.dataset.type;

            // Show/hide tab-specific controls
            var adsbCtrl = document.getElementById('adsb-controls');
            if (adsbCtrl) {
                if (activeFilter === 'aircraft') {
                    adsbCtrl.classList.remove('hidden');
                    loadADSBDevices();
                } else {
                    adsbCtrl.classList.add('hidden');
                }
            }

            var aisCtrl = document.getElementById('ais-controls');
            if (aisCtrl) {
                if (activeFilter === 'vessel') {
                    aisCtrl.classList.remove('hidden');
                    loadAISDevices();
                } else {
                    aisCtrl.classList.add('hidden');
                }
            }

            var droneCtrl = document.getElementById('drone-controls');
            if (droneCtrl) {
                if (activeFilter === 'drone') {
                    droneCtrl.classList.remove('hidden');
                    loadDroneStatus();
                } else {
                    droneCtrl.classList.add('hidden');
                }
            }

            var aprsCtrl = document.getElementById('aprs-controls');
            if (aprsCtrl) {
                if (activeFilter === 'aprs') {
                    aprsCtrl.classList.remove('hidden');
                    updateAPRSMessages();
                } else {
                    aprsCtrl.classList.add('hidden');
                }
            }

            if (activeFilter === 'noaa') {
                renderNOAAPanel();
            } else {
                updateList();
            }
        });
    });

    // ── ADS-B device loading ──
    var adsbDevicesLoaded = false;
    function loadADSBDevices() {
        var sel = document.getElementById('adsb-device');
        if (!sel) return;
        fetch('/api/devices')
            .then(function(r) { return r.json(); })
            .then(function(devs) {
                var cur = sel.value;
                sel.innerHTML = '<option value="-1">Select Source</option>' +
                    '<option value="-2">Online (OpenSky)</option>';
                (devs || []).forEach(function(d) {
                    sel.innerHTML += '<option value="' + d.index + '">Device ' + d.index + '</option>';
                });
                sel.value = cur;
                adsbDevicesLoaded = true;
            })
            .catch(function() {});

        // Also update button state
        fetch('/api/status')
            .then(function(r) { return r.json(); })
            .then(function(statuses) {
                var adsbStatus = (statuses || []).find(function(s) { return s.name === 'adsb'; });
                var btn = document.getElementById('adsb-toggle');
                if (adsbStatus && btn) {
                    if (adsbStatus.running) {
                        btn.textContent = 'Stop';
                        btn.classList.remove('start');
                        btn.classList.add('stop');
                    } else {
                        btn.textContent = 'Start';
                        btn.classList.remove('stop');
                        btn.classList.add('start');
                    }
                }
            })
            .catch(function() {});

        // Load aircraft DB status
        loadAircraftDBStatus();
    }

    // ── AIS device loading ──
    function loadAISDevices() {
        var sel = document.getElementById('ais-device');
        if (!sel) return;
        fetch('/api/devices')
            .then(function(r) { return r.json(); })
            .then(function(devs) {
                var cur = sel.value;
                sel.innerHTML = '<option value="-1">Select Source</option>' +
                    '<option value="-2">Online (AISStream)</option>';
                (devs || []).forEach(function(d) {
                    sel.innerHTML += '<option value="' + d.index + '">Device ' + d.index + '</option>';
                });
                sel.value = cur;
            })
            .catch(function() {});

        fetch('/api/status')
            .then(function(r) { return r.json(); })
            .then(function(statuses) {
                var aisStatus = (statuses || []).find(function(s) { return s.name === 'ais'; });
                var btn = document.getElementById('ais-toggle');
                if (aisStatus && btn) {
                    if (aisStatus.running) {
                        btn.textContent = 'Stop';
                        btn.classList.remove('start');
                        btn.classList.add('stop');
                    } else {
                        btn.textContent = 'Start';
                        btn.classList.remove('stop');
                        btn.classList.add('start');
                    }
                }
            })
            .catch(function() {});
    }

    // ── Drone status loading ──
    var droneIfacesLoaded = false;
    function loadDroneInterfaces() {
        if (droneIfacesLoaded) return;
        var sel = document.getElementById('drone-iface');
        if (!sel) return;
        fetch('/api/remoteid/interfaces')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                droneIfacesLoaded = true;
                var ifaces = (data && data.interfaces) || [];
                var current = (data && data.current) || '';
                if (!ifaces.length) {
                    sel.innerHTML = '<option value="">No adapters found</option>';
                    return;
                }
                sel.innerHTML = ifaces.map(function(i) {
                    var label = (i.wireless ? '📶 ' : '') + (i.description || i.name);
                    return '<option value="' + i.name.replace(/"/g, '&quot;') + '">' + label + '</option>';
                }).join('');
                if (current) sel.value = current;
            })
            .catch(function() {
                sel.innerHTML = '<option value="">(failed to enumerate)</option>';
            });
    }

    function loadDroneStats() {
        var box = document.getElementById('drone-stats');
        if (!box) return;
        fetch('/api/remoteid/stats')
            .then(function(r) { return r.json(); })
            .then(function(s) {
                if (!s.running) {
                    box.innerHTML = '<span style="color:#64748b">Sniffer not running.</span>';
                    return;
                }
                var ago = function(ts) { return ts ? Math.round(Date.now()/1000 - ts) + 's ago' : 'never'; };
                var wifiStale = (s.frames_total === 0 || (s.last_frame_at && Date.now()/1000 - s.last_frame_at > 30));
                var wifiColor = wifiStale ? '#fca5a5' : '#6ee7b7';
                var wifiRidColor = (s.frames_rid > 0) ? '#6ee7b7' : '#fbbf24';

                var html = '';
                html += '<div style="color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px">WiFi sniff</div>';
                html += '<div style="color:' + wifiColor + '">📡 Frames: ' + s.frames_total +
                    ' <span style="color:#64748b">(mgmt ' + s.frames_mgmt + ', last ' + ago(s.last_frame_at) + ')</span></div>';
                html += '<div style="color:' + wifiRidColor + '">🛸 Drone RID: ' + s.frames_rid +
                    ' <span style="color:#64748b">(last ' + ago(s.last_rid_at) + ')</span></div>';

                html += '<div style="color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;margin-top:6px;margin-bottom:2px">Bluetooth LE</div>';
                if (!s.ble_running) {
                    html += '<div style="color:#fca5a5">BLE scanner not running (check that Bluetooth is on).</div>';
                } else {
                    var bleStale = (s.ble_frames_total === 0 || (s.ble_last_frame_at && Date.now()/1000 - s.ble_last_frame_at > 30));
                    var bleColor = bleStale ? '#fca5a5' : '#6ee7b7';
                    var bleRidColor = (s.ble_frames_rid > 0) ? '#6ee7b7' : '#fbbf24';
                    html += '<div style="color:' + bleColor + '">📶 Adv frames: ' + s.ble_frames_total +
                        ' <span style="color:#64748b">(last ' + ago(s.ble_last_frame_at) + ')</span></div>';
                    html += '<div style="color:' + bleRidColor + '">🛸 Drone RID: ' + s.ble_frames_rid +
                        ' <span style="color:#64748b">(last ' + ago(s.ble_last_rid_at) + ')</span></div>';
                }

                if (s.frames_total === 0 && (!s.ble_running || s.ble_frames_total === 0)) {
                    html += '<div style="color:#fca5a5;margin-top:4px">No packets on either band — check adapter / Bluetooth.</div>';
                } else if (s.frames_total > 0 && s.frames_mgmt === 0) {
                    html += '<div style="color:#fbbf24;margin-top:4px">WiFi packets flowing but no beacons — adapter likely not in monitor mode.</div>';
                }
                box.innerHTML = html;
            })
            .catch(function() {});
    }

    function loadDroneStatus() {
        loadDroneInterfaces();
        loadDroneStats();
        fetch('/api/status')
            .then(function(r) { return r.json(); })
            .then(function(statuses) {
                var droneStatus = (statuses || []).find(function(s) { return s.name === 'drone'; });
                var btn = document.getElementById('drone-toggle');
                if (droneStatus && btn) {
                    if (droneStatus.running) {
                        btn.textContent = 'Stop';
                        btn.classList.remove('start');
                        btn.classList.add('stop');
                    } else {
                        btn.textContent = 'Start';
                        btn.classList.remove('stop');
                        btn.classList.add('start');
                    }
                }
            })
            .catch(function() {});
    }

    function loadAircraftDBStatus() {
        fetch('/api/aircraft/status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var el = document.getElementById('adsb-db-status');
                if (el) {
                    if (data.count > 0) {
                        el.textContent = 'Aircraft DB: ' + data.count.toLocaleString() + ' aircraft';
                        el.style.color = '#6ee7b7';
                    } else {
                        el.textContent = 'Aircraft DB: not loaded';
                        el.style.color = '#64748b';
                    }
                }
            })
            .catch(function() {});
    }

    document.getElementById('adsb-db-import').addEventListener('click', function() {
        var btn = this;
        var status = document.getElementById('adsb-db-status');
        btn.disabled = true;
        btn.textContent = 'Importing...';
        status.textContent = 'Downloading from OpenSky Network...';
        status.style.color = '#38bdf8';

        fetch('/api/aircraft/import', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                btn.disabled = false;
                btn.textContent = 'Import Database';
                if (data.error) {
                    status.textContent = 'Error: ' + data.error;
                    status.style.color = '#fca5a5';
                } else {
                    status.textContent = 'Aircraft DB: ' + data.count.toLocaleString() + ' aircraft';
                    status.style.color = '#6ee7b7';
                }
            })
            .catch(function(err) {
                btn.disabled = false;
                btn.textContent = 'Import Database';
                status.textContent = 'Import failed: ' + err.message;
                status.style.color = '#fca5a5';
            });
    });

    // ── Close detail panel ──
    document.getElementById('close-detail').addEventListener('click', function() {
        selectedId = null;
        document.getElementById('detail-panel').classList.add('hidden');
        updateList();
    });

    // ── Clear Map ──
    document.getElementById('clear-map-btn').addEventListener('click', function() {
        // Remove all target markers
        Object.keys(markers).forEach(function(id) {
            map.removeLayer(markers[id]);
            delete markers[id];
        });
        // Remove all APRS markers
        Object.keys(aprsMarkers).forEach(function(id) {
            map.removeLayer(aprsMarkers[id]);
            delete aprsMarkers[id];
        });
        // Clear data arrays
        targets = [];
        aprsStations = [];
        aprsMessages = [];
        selectedId = null;
        document.getElementById('detail-panel').classList.add('hidden');
        updateStats();
        updateList();
    });

    // ══════════════════════════════════════
    // ── APRS Map + List ──
    // ══════════════════════════════════════

    var APRS_COLORS = { 'IS': '#00aacc', 'RF': '#00ff9d', 'UV-Pro': '#ffd166', 'TX': '#ff6b6b' };

    function aprsIcon(station) {
        // Use real APRS symbol from spritesheet if available
        var symbolTag = '';
        if (station.symbol && station.symbol.length === 2 && typeof getAPRSSymbolImageTag === 'function') {
            symbolTag = getAPRSSymbolImageTag(station.symbol, 24);
        }
        if (!symbolTag) {
            // Fallback to colored triangle
            var color = APRS_COLORS[station.source] || '#aaaaaa';
            symbolTag = '<div style="color:' + color + ';font-size:16px;">&#x25B2;</div>';
        }
        return L.divIcon({
            html: '<div class="aprs-marker-wrap">' + symbolTag + '</div>',
            className: '',
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });
    }

    function aprsSymbolHTML(symbol, size) {
        size = size || 24;
        if (symbol && symbol.length === 2 && typeof getAPRSSymbolImageTag === 'function') {
            var tag = getAPRSSymbolImageTag(symbol, size);
            if (tag) return tag;
        }
        return '<span style="font-size:' + size + 'px;">&#x25B2;</span>';
    }

    function updateAPRSMap() {
        var activeIds = new Set();
        var bounds = map.getBounds();

        aprsStations.forEach(function(s) {
            if (s.lat === 0 && s.lon === 0) return;
            var id = 'aprs-' + s.callsign;

            // Only show stations within the current map view
            if (!bounds.contains([s.lat, s.lon])) {
                // Remove marker if it exists but is now out of view
                if (aprsMarkers[id]) {
                    map.removeLayer(aprsMarkers[id]);
                    delete aprsMarkers[id];
                }
                return;
            }

            activeIds.add(id);

            if (aprsMarkers[id]) {
                aprsMarkers[id].setLatLng([s.lat, s.lon]);
                aprsMarkers[id].setIcon(aprsIcon(s));
            } else {
                var m = L.marker([s.lat, s.lon], { icon: aprsIcon(s) })
                    .addTo(map)
                    .on('click', function() { selectTarget('aprs-' + s.callsign); });
                aprsMarkers[id] = m;
            }

            aprsMarkers[id].bindTooltip(s.callsign + ' [' + s.source + ']', {
                permanent: false,
                direction: 'top',
            });
        });

        // Remove stale APRS markers
        Object.keys(aprsMarkers).forEach(function(id) {
            if (!activeIds.has(id)) {
                map.removeLayer(aprsMarkers[id]);
                delete aprsMarkers[id];
            }
        });
    }

    // Re-render APRS markers when map view changes
    map.on('moveend', function() {
        updateAPRSMap();
        updateOpenSkyBounds();
        updateAISStreamBounds();
    });

    // Debounced bounds update for online feeds
    var openSkyBoundsTimer = null;
    function updateOpenSkyBounds() {
        if (openSkyBoundsTimer) clearTimeout(openSkyBoundsTimer);
        openSkyBoundsTimer = setTimeout(function() {
            var b = map.getBounds();
            fetch('/api/aircraft/bounds', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    lamin: b.getSouth(),
                    lomin: b.getWest(),
                    lamax: b.getNorth(),
                    lomax: b.getEast()
                })
            }).catch(function() {});
        }, 500);
    }

    var aisBoundsTimer = null;
    function updateAISStreamBounds() {
        if (aisBoundsTimer) clearTimeout(aisBoundsTimer);
        aisBoundsTimer = setTimeout(function() {
            var b = map.getBounds();
            fetch('/api/ais/bounds', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    lamin: b.getSouth(),
                    lomin: b.getWest(),
                    lamax: b.getNorth(),
                    lomax: b.getEast()
                })
            }).catch(function() {});
        }, 2000); // 2s debounce — AISStream doesn't like rapid re-subscriptions
    }

    // ══════════════════════════════════════
    // ── SDR Setup Panel ──
    // ══════════════════════════════════════

    let devices = [];
    let moduleStatuses = [];

    function openSetup() {
        document.getElementById('setup-overlay').classList.remove('hidden');
        loadDevices();
        loadStatus();
    }

    function closeSetup() {
        document.getElementById('setup-overlay').classList.add('hidden');
    }

    document.getElementById('setup-btn').addEventListener('click', openSetup);
    document.getElementById('close-setup').addEventListener('click', closeSetup);
    document.getElementById('setup-overlay').addEventListener('click', function(e) {
        if (e.target === this) closeSetup();
    });

    function loadDevices() {
        var loading = document.getElementById('devices-loading');
        var errEl = document.getElementById('devices-error');
        var listEl = document.getElementById('devices-list');
        var controls = document.getElementById('module-controls');

        loading.style.display = 'block';
        errEl.classList.add('hidden');
        listEl.classList.add('hidden');

        fetch('/api/devices')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                loading.style.display = 'none';

                if (data.error) {
                    errEl.textContent = data.error;
                    errEl.classList.remove('hidden');
                    controls.classList.add('hidden');
                    return;
                }

                devices = data;
                renderDevices();
                populateSelects();
                controls.classList.remove('hidden');
            })
            .catch(function(err) {
                loading.style.display = 'none';
                errEl.textContent = 'Failed to scan devices: ' + err.message;
                errEl.classList.remove('hidden');
            });
    }

    function renderDevices() {
        var listEl = document.getElementById('devices-list');
        listEl.classList.remove('hidden');

        var html = '<h3>Detected RTL-SDR Devices</h3>';
        if (devices.length === 0) {
            html += '<p style="color:#64748b;font-size:13px;">No RTL-SDR devices detected. Plug in your dongles and click SDR Setup again.</p>';
        }
        devices.forEach(function(d) {
            var statusClass = d.in_use ? 'in-use' : 'available';
            var statusText = d.in_use ? d.assigned_to.toUpperCase() : 'Available';
            html += '<div class="device-card">' +
                '<div class="device-index">' + d.index + '</div>' +
                '<div class="device-info">' +
                    '<div class="device-name">' + escHtml(d.manufacturer + ' ' + d.product) + '</div>' +
                    '<div class="device-detail">SN: ' + escHtml(d.serial || 'N/A') + ' &middot; Device #' + d.index + '</div>' +
                '</div>' +
                '<span class="device-status ' + statusClass + '">' + statusText + '</span>' +
            '</div>';
        });
        listEl.innerHTML = html;
    }

    function populateSelects() {
        var selects = ['aprs-sdr-device'];
        selects.forEach(function(id) {
            var sel = document.getElementById(id);
            // Preserve current value
            var current = sel.value;
            sel.innerHTML = '<option value="-1">Disabled</option>';
            devices.forEach(function(d) {
                var label = '#' + d.index + ' — ' + d.manufacturer + ' ' + d.product;
                if (d.serial) label += ' (SN: ' + d.serial + ')';
                var opt = document.createElement('option');
                opt.value = d.index;
                opt.textContent = label;
                sel.appendChild(opt);
            });
            // Restore selection if still valid
            if (current && sel.querySelector('option[value="' + current + '"]')) {
                sel.value = current;
            }
        });

        // If we have status info, pre-select the active devices
        moduleStatuses.forEach(function(st) {
            if (st.running && st.device >= 0) {
                var selId = st.name + '-device';
                var sel = document.getElementById(selId);
                if (sel) sel.value = st.device;
            }
        });
    }

    function loadStatus() {
        fetch('/api/status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                moduleStatuses = data;
                updateToggleButtons();
                // Pre-select devices in dropdowns
                if (devices.length > 0) populateSelects();
            });
    }

    function updateToggleButtons() {
        moduleStatuses.forEach(function(st) {
            var btn = document.getElementById(st.name + '-toggle');
            if (!btn) return;
            if (st.running) {
                btn.textContent = 'Stop';
                btn.className = 'module-toggle stop';
            } else {
                btn.textContent = 'Start';
                btn.className = 'module-toggle start';
            }
        });

        // Show errors
        var statusEl = document.getElementById('module-status');
        var errMsgs = moduleStatuses.filter(function(s) { return s.error; });
        if (errMsgs.length > 0) {
            statusEl.innerHTML = errMsgs.map(function(s) {
                return '<div class="status-msg status-err">' + s.name.toUpperCase() + ': ' + escHtml(s.error) + '</div>';
            }).join('');
        } else {
            statusEl.innerHTML = '';
        }
    }

    // Module start/stop buttons
    document.querySelectorAll('.module-toggle').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var module = btn.dataset.module;
            var isRunning = btn.classList.contains('stop');

            if (isRunning) {
                // Stop
                btn.disabled = true;
                btn.textContent = 'Stopping...';
                fetch('/api/stop', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({module: module})
                })
                .then(function(r) { return r.json(); })
                .then(function() {
                    btn.disabled = false;
                    loadStatus();
                    loadDevices();
                })
                .catch(function() { btn.disabled = false; loadStatus(); });
            } else {
                // Start
                var deviceIdx = -1;
                var droneIface = '';
                if (module === 'drone') {
                    var ifaceSel = document.getElementById('drone-iface');
                    droneIface = ifaceSel ? ifaceSel.value : '';
                    if (!droneIface) {
                        showSetupMsg('Select a WiFi adapter for Drone RID first', true);
                        return;
                    }
                } else {
                    var sel = document.getElementById(module + '-device');
                    if (sel) {
                        deviceIdx = parseInt(sel.value, 10);
                        // -2 = online feed (OpenSky), -1 = not selected
                        if (deviceIdx === -1) {
                            showSetupMsg('Select a device for ' + module.toUpperCase() + ' first', true);
                            return;
                        }
                    }
                }

                btn.disabled = true;
                btn.textContent = 'Starting...';
                var startBody = {module: module, device: deviceIdx};
                if (module === 'drone') {
                    startBody.interface = droneIface;
                }
                // Always include the visible map bounds — online feeds use it
                // to scope queries, and the native ADS-B decoder uses the
                // box centre as a CPR reference so positions decode from a
                // single message instead of waiting for an odd/even pair.
                if (module === 'adsb' || module === 'ais' || deviceIdx === -2) {
                    var b = map.getBounds();
                    startBody.lamin = b.getSouth();
                    startBody.lomin = b.getWest();
                    startBody.lamax = b.getNorth();
                    startBody.lomax = b.getEast();
                }
                fetch('/api/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(startBody)
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    btn.disabled = false;
                    if (data.error) {
                        showSetupMsg(data.error, true);
                    } else {
                        var srcLabel;
                        if (module === 'drone') {
                            srcLabel = droneIface;
                        } else {
                            srcLabel = deviceIdx === -2 ? 'Online (OpenSky)' : 'device #' + deviceIdx;
                        }
                        showSetupMsg(module.toUpperCase() + ' started on ' + srcLabel, false);
                        // If starting online feed, send current map bounds immediately
                        if (module === 'adsb' && deviceIdx === -2) {
                            setTimeout(updateOpenSkyBounds, 500);
                        }
                        if (module === 'ais' && deviceIdx === -2) {
                            setTimeout(updateAISStreamBounds, 2000);
                        }
                    }
                    loadStatus();
                    loadDevices();
                })
                .catch(function(err) {
                    btn.disabled = false;
                    showSetupMsg('Failed: ' + err.message, true);
                    loadStatus();
                });
            }
        });
    });

    function showSetupMsg(msg, isError) {
        var el = document.getElementById('module-status');
        var cls = isError ? 'status-err' : 'status-ok';
        el.innerHTML = '<div class="status-msg ' + cls + '">' + escHtml(msg) + '</div>';
        setTimeout(function() {
            if (el.querySelector('.status-msg')) {
                el.innerHTML = '';
            }
        }, 5000);
    }

    // Poll status every 5 seconds while setup is open
    setInterval(function() {
        if (!document.getElementById('setup-overlay').classList.contains('hidden')) {
            loadStatus();
        }
    }, 5000);

    // Refresh the drone-RID counters every 3s while the Drones tab is active.
    setInterval(function() {
        if (activeFilter === 'drone') loadDroneStats();
    }, 3000);

    // ══════════════════════════════════════
    // ── NOAA satellite live tracking removed (was log noise; tracker disabled).

    // ══════════════════════════════════════
    // ── NWR Tower Map Layer ──
    // ══════════════════════════════════════

    var nwrTowerMarkers = [];
    var nwrTowersLoaded = false;
    var nwrTowerLayer = L.layerGroup().addTo(map);

    function loadNWRTowers() {
        if (nwrTowersLoaded) return;
        nwrTowersLoaded = true;

        fetch('/api/noaa/radio/stations')
            .then(function(r) { return r.json(); })
            .then(function(stations) {
                if (!stations || !Array.isArray(stations)) return;

                stations.forEach(function(s) {
                    if (s.status !== 'NORMAL') return;

                    var icon = L.divIcon({
                        html: '<div class="nwr-tower-icon">&#x1F5FC;</div>',
                        className: '',
                        iconSize: [20, 20],
                        iconAnchor: [10, 10],
                    });

                    var marker = L.marker([s.lat, s.lon], { icon: icon })
                        .bindTooltip(s.callsign + ' — ' + s.name + ', ' + s.state +
                            '\\n' + s.frequency.toFixed(3) + ' MHz · ' + s.power + 'W' +
                            '\\nWFO: ' + s.wfo, {
                            direction: 'top',
                        });

                    marker.on('click', function() {
                        showNWRTunePopup(s);
                    });

                    nwrTowerLayer.addLayer(marker);
                });

                log_nwr_count(stations.length);
            });
    }

    function log_nwr_count(count) {
        console.log('[SkyWatch] Loaded ' + count + ' NWR transmitter towers');
    }

    function buildNWRPopupHeader(station) {
        return '<div class="nwr-popup">' +
            '<div class="nwr-popup-header">' +
                '<span class="nwr-popup-call">' + escHtml(station.callsign) + '</span>' +
                '<span class="nwr-popup-freq">' + station.frequency.toFixed(3) + ' MHz</span>' +
            '</div>' +
            '<div class="nwr-popup-location">' + escHtml(station.name) + ', ' + escHtml(station.state) +
                ' &middot; ' + station.power + 'W &middot; WFO: ' + escHtml(station.wfo) + '</div>' +
            '<div class="nwr-popup-controls">' +
                '<label style="font-size:11px;color:#94a3b8">Device:</label>' +
                '<input type="number" id="nwr-popup-device" value="0" min="0" max="9" ' +
                    'style="width:40px;padding:3px 6px;background:#0f172a;border:1px solid #334155;border-radius:4px;color:#e0e6ed;font-size:12px" />' +
                '<button onclick="window.skywatch.tuneNWR(' + station.frequency + ', parseInt(document.getElementById(\'nwr-popup-device\').value))" ' +
                    'class="nwr-listen-btn">Listen</button>' +
            '</div>';
    }

    function buildWeatherHTML(data) {
        var html = '';

        // Forecast
        if (data.forecast) {
            var fc = typeof data.forecast === 'string' ? JSON.parse(data.forecast) : data.forecast;
            var periods = (fc.properties || {}).periods || [];
            if (periods.length > 0) {
                html += '<div class="nwr-section-title">Forecast</div>';
                periods.slice(0, 3).forEach(function(p) {
                    html += '<div class="nwr-forecast-period">' +
                        '<div class="nwr-fc-name">' + escHtml(p.name) + '</div>' +
                        '<div class="nwr-fc-detail">' +
                            '<span class="nwr-fc-temp">' + p.temperature + '&deg;' + p.temperatureUnit + '</span>' +
                            ' &middot; ' + escHtml(p.shortForecast) +
                        '</div>' +
                        (p.detailedForecast ? '<div class="nwr-fc-desc">' + escHtml(p.detailedForecast) + '</div>' : '') +
                    '</div>';
                });
            }
        }

        // Alerts
        if (data.alerts) {
            var alerts = typeof data.alerts === 'string' ? JSON.parse(data.alerts) : data.alerts;
            var features = (alerts.features || []);
            if (features.length > 0) {
                html += '<div class="nwr-section-title" style="color:#fca5a5">Active Alerts (' + features.length + ')</div>';
                features.forEach(function(f) {
                    var p = f.properties || {};
                    var sevClass = 'nwr-alert-' + (p.severity || 'minor').toLowerCase();
                    var expires = p.expires ? new Date(p.expires).toLocaleString() : '';
                    html += '<div class="nwr-alert ' + sevClass + '">' +
                        '<div class="nwr-alert-event">' + escHtml(p.event || 'Alert') + '</div>' +
                        '<div class="nwr-alert-headline">' + escHtml(p.headline || '') + '</div>' +
                        (p.description ? '<div class="nwr-alert-desc">' + escHtml(p.description).replace(/\n/g, '<br>') + '</div>' : '') +
                        (p.instruction ? '<div class="nwr-alert-instr">' + escHtml(p.instruction).replace(/\n/g, '<br>') + '</div>' : '') +
                        (expires ? '<div class="nwr-alert-expires">Expires: ' + expires + '</div>' : '') +
                    '</div>';
                });
            } else {
                html += '<div class="nwr-section-title" style="color:#6ee7b7">No Active Alerts</div>';
            }
        }

        return html || '<div style="color:#64748b;font-size:11px">No weather data available</div>';
    }

    function showNWRTunePopup(station) {
        var headerHtml = buildNWRPopupHeader(station);
        var loadingContent = headerHtml +
            '<div style="margin-top:8px;color:#64748b;font-size:11px">Loading weather data...</div></div>';

        var popup = L.popup({ maxWidth: 360, minWidth: 300 })
            .setLatLng([station.lat, station.lon])
            .setContent(loadingContent)
            .openOn(map);

        fetch('/api/noaa/weather?lat=' + station.lat + '&lon=' + station.lon)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var fullHtml = headerHtml +
                    '<div style="margin-top:8px">' + buildWeatherHTML(data) + '</div></div>';
                popup.setContent(fullHtml);
            })
            .catch(function(err) {
                var fullHtml = headerHtml +
                    '<div style="margin-top:8px;color:#fca5a5;font-size:11px">Failed to load weather data</div></div>';
                popup.setContent(fullHtml);
            });
    }

    window.skywatch.tuneNWR = function(freq, device) {
        // Stop any existing stream
        fetch('/api/noaa/radio/stop', { method: 'POST' }).then(function() {
            // Start on selected frequency
            fetch('/api/noaa/radio/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ frequency: freq, device: device || 0 })
            }).then(function() {
                map.closePopup();
                // Switch to NOAA tab to show audio player
                document.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
                var noaaBtn = document.querySelector('.filter-btn[data-type="noaa"]');
                if (noaaBtn) { noaaBtn.classList.add('active'); }
                activeFilter = 'noaa';
                setTimeout(renderNOAAPanel, 1500);
            });
        });
    };

    // Load towers on startup — show at zoom level 4+
    loadNWRTowers();
    map.on('zoomend', function() {
        if (map.getZoom() >= 8) {
            if (!map.hasLayer(nwrTowerLayer)) map.addLayer(nwrTowerLayer);
        } else {
            if (map.hasLayer(nwrTowerLayer)) map.removeLayer(nwrTowerLayer);
        }
    });
    // Initial visibility check
    if (map.getZoom() < 8) map.removeLayer(nwrTowerLayer);

    // ══════════════════════════════════════
    // ── NOAA Satellite Tab ──
    // ══════════════════════════════════════

    var noaaCaptureRunning = false;
    var savedNWRDevice = '0';
    var savedNWRFreq = '162.400';
    var savedNOAADevice = '-1';
    var savedNOAASat = '137.1000';
    var savedNOAADur = '900';

    function renderNOAAPanel() {
        if (activeFilter !== 'noaa') return;
        var list = document.getElementById('target-list');

        var el;
        el = document.getElementById('nwr-device'); if (el) savedNWRDevice = el.value;
        el = document.getElementById('nwr-freq'); if (el) savedNWRFreq = el.value;

        var html = '<div class="noaa-panel">';
        html += '<div class="noaa-section">';
        html += '<h3 class="noaa-heading">Weather Radio (NWR 162 MHz)</h3>';
        html += '<div class="noaa-controls">';
        html += '<div class="noaa-ctrl-row">' +
            '<select id="nwr-freq" class="device-select" style="flex:1">' +
                '<option value="162.400">WX1 — 162.400 MHz</option>' +
                '<option value="162.425">WX2 — 162.425 MHz</option>' +
                '<option value="162.450">WX3 — 162.450 MHz</option>' +
                '<option value="162.475">WX4 — 162.475 MHz</option>' +
                '<option value="162.500">WX5 — 162.500 MHz</option>' +
                '<option value="162.525">WX6 — 162.525 MHz</option>' +
                '<option value="162.550">WX7 — 162.550 MHz</option>' +
            '</select>' +
            '<input type="number" id="nwr-device" class="tx-input" value="' + savedNWRDevice + '" style="width:45px" title="RTL-SDR device" />' +
        '</div>';
        html += '<div class="noaa-ctrl-row" style="margin-top:6px">' +
            '<button id="nwr-listen" class="noaa-btn">Listen</button>' +
            '<button id="nwr-stop" class="noaa-btn noaa-btn-stop" style="display:none">Stop</button>' +
            '<button id="nwr-scan" class="noaa-btn" style="background:#1e293b;color:#94a3b8">Scan All</button>' +
        '</div>';
        html += '<div id="nwr-status-line" style="margin-top:6px;font-size:11px;color:#64748b"></div>';
        html += '<audio id="nwr-audio" style="display:none" autoplay></audio>';
        html += '<div id="nwr-scan-results"></div>';
        html += '</div></div></div>';
        list.innerHTML = html;

        var nwrFreqEl = document.getElementById('nwr-freq');
        if (nwrFreqEl) nwrFreqEl.value = savedNWRFreq;

        // ── NWR button handlers ──
        var nwrListen = document.getElementById('nwr-listen');
        var nwrStopBtn = document.getElementById('nwr-stop');
        var nwrScanBtn = document.getElementById('nwr-scan');

        if (nwrListen) {
            fetch('/api/noaa/radio/status')
                .then(function(r) { return r.json(); })
                .then(function(st) {
                    if (st.active) {
                        nwrListen.style.display = 'none';
                        nwrStopBtn.style.display = '';
                        var statusLine = document.getElementById('nwr-status-line');
                        if (statusLine) statusLine.innerHTML = '<span style="color:#6ee7b7">Listening: ' + st.channel + ' (' + st.signal_db.toFixed(1) + ' dB)</span>';
                        var audio = document.getElementById('nwr-audio');
                        if (audio && !audio.src) {
                            audio.src = '/api/noaa/radio/stream';
                            audio.style.display = 'block';
                            audio.style.width = '100%';
                            audio.style.marginTop = '6px';
                            audio.style.height = '32px';
                        }
                    }
                });

            nwrListen.addEventListener('click', function() {
                var freq = parseFloat(document.getElementById('nwr-freq').value);
                var dev = parseInt(document.getElementById('nwr-device').value) || 0;
                nwrListen.textContent = 'Tuning...';
                nwrListen.disabled = true;
                fetch('/api/noaa/radio/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ frequency: freq, device: dev })
                }).then(function() {
                    setTimeout(function() {
                        nwrListen.style.display = 'none';
                        nwrStopBtn.style.display = '';
                        nwrListen.textContent = 'Listen';
                        nwrListen.disabled = false;
                        var audio = document.getElementById('nwr-audio');
                        if (audio) {
                            audio.src = '/api/noaa/radio/stream';
                            audio.style.display = 'block';
                            audio.style.width = '100%';
                            audio.style.marginTop = '6px';
                            audio.style.height = '32px';
                        }
                        renderNOAAPanel();
                    }, 1500);
                });
            });
        }

        if (nwrStopBtn) {
            nwrStopBtn.addEventListener('click', function() {
                fetch('/api/noaa/radio/stop', { method: 'POST' }).then(function() {
                    var audio = document.getElementById('nwr-audio');
                    if (audio) { audio.pause(); audio.src = ''; audio.style.display = 'none'; }
                    renderNOAAPanel();
                });
            });
        }

        if (nwrScanBtn) {
            nwrScanBtn.addEventListener('click', function() {
                var dev = parseInt(document.getElementById('nwr-device').value) || 0;
                nwrScanBtn.textContent = 'Scanning...';
                nwrScanBtn.disabled = true;
                fetch('/api/noaa/radio/scan', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ device: dev })
                }).then(function(r) { return r.json(); }).then(function(results) {
                    nwrScanBtn.textContent = 'Scan All';
                    nwrScanBtn.disabled = false;
                    var box = document.getElementById('nwr-scan-results');
                    if (!box) return;
                    box.innerHTML = (results || []).map(function(c) {
                        var color = c.active ? '#6ee7b7' : '#64748b';
                        return '<div style="font-size:11px;color:' + color + ';padding:2px 0">' +
                            c.name + ' — ' + c.frequency_mhz.toFixed(3) + ' MHz · ' +
                            c.signal_db.toFixed(1) + ' dB' +
                            (c.active ? ' · ACTIVE' : '') +
                        '</div>';
                    }).join('');
                });
            });
        }
    }

    // Refresh NOAA tab every 10 seconds when active
    setInterval(function() {
        if (activeFilter === 'noaa') renderNOAAPanel();
    }, 10000);

    // (NOAA capture controls are now in the NOAA tab panel — see renderNOAAPanel)

    // ══════════════════════════════════════
    // ── APRS Transmit Controls ──
    // ══════════════════════════════════════

    var txLat = 0, txLon = 0;

    function loadAPRSConfig() {
        fetch('/api/aprs/config')
            .then(function(r) { return r.json(); })
            .then(function(cfg) {
                if (cfg.callsign && cfg.callsign !== 'N0CALL') {
                    document.getElementById('tx-callsign').value = cfg.callsign;
                }
                if (cfg.ssid !== undefined) {
                    document.getElementById('tx-ssid').value = cfg.ssid;
                }
                if (cfg.lat && cfg.lon) {
                    txLat = cfg.lat;
                    txLon = cfg.lon;
                    document.getElementById('tx-pos-display').textContent =
                        cfg.lat.toFixed(5) + ', ' + cfg.lon.toFixed(5);
                }
                if (cfg.comment) {
                    document.getElementById('tx-comment').value = cfg.comment;
                }
            })
            .catch(function() {});
    }

    // APRS Settings popup
    window.skywatch.openAPRSSettings = function() {
        var overlay = document.getElementById('aprs-settings-overlay');
        if (overlay) {
            overlay.classList.remove('hidden');
            overlay.style.display = 'flex';
            loadAPRSConfig();
            fetch('/api/devices').then(function(r) { return r.json(); }).then(function(devs) {
                var sel = document.getElementById('aprs-sdr-device');
                if (!sel) return;
                var cur = sel.value;
                sel.innerHTML = '<option value="-1">Disabled</option>';
                (devs || []).forEach(function(d) {
                    sel.innerHTML += '<option value="' + d.index + '">Device ' + d.index + '</option>';
                });
                sel.value = cur;
            }).catch(function() {});
        }
    };

    window.skywatch.closeAPRSSettings = function() {
        var overlay = document.getElementById('aprs-settings-overlay');
        if (overlay) { overlay.classList.add('hidden'); overlay.style.display = ''; }
    };

    document.getElementById('tx-save-call').addEventListener('click', function() {
        var call = document.getElementById('tx-callsign').value.trim().toUpperCase();
        var ssid = parseInt(document.getElementById('tx-ssid').value) || 9;
        if (!call) {
            showTXStatus('Enter a callsign', true);
            return;
        }
        fetch('/api/aprs/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ callsign: call, ssid: ssid })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                showTXStatus(data.error, true);
            } else {
                showTXStatus('Callsign set: ' + call + '-' + ssid + ' (passcode auto-computed)', false);
            }
        });
    });

    document.getElementById('tx-set-pos').addEventListener('click', function() {
        var center = map.getCenter();
        txLat = center.lat;
        txLon = center.lng;
        document.getElementById('tx-pos-display').textContent =
            txLat.toFixed(5) + ', ' + txLon.toFixed(5);
    });

    document.getElementById('tx-beacon').addEventListener('click', function() {
        var btn = this;
        if (txLat === 0 && txLon === 0) {
            showTXStatus('Set position first (click "Set from map center")', true);
            return;
        }
        btn.disabled = true;
        btn.textContent = 'Sending...';
        fetch('/api/aprs/beacon', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                lat: txLat,
                lon: txLon,
                symbol: document.getElementById('tx-symbol').value,
                comment: document.getElementById('tx-comment').value
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.textContent = 'Send Beacon';
            if (data.error) {
                showTXStatus(data.error, true);
            } else {
                showTXStatus('Beacon sent!', false);
            }
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = 'Send Beacon';
            showTXStatus('Failed: ' + err.message, true);
        });
    });

    document.getElementById('tx-send-msg').addEventListener('click', function() {
        var btn = this;
        var to = document.getElementById('tx-msg-to').value.trim();
        var text = document.getElementById('tx-msg-text').value.trim();
        if (!to || !text) {
            showTXStatus('Enter callsign and message', true);
            return;
        }
        btn.disabled = true;
        btn.textContent = '...';
        fetch('/api/aprs/message', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ to: to, text: text })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.textContent = 'Send';
            if (data.error) {
                showTXStatus(data.error, true);
            } else {
                showTXStatus('Message sent to ' + to, false);
                document.getElementById('tx-msg-text').value = '';
            }
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = 'Send';
            showTXStatus('Failed: ' + err.message, true);
        });
    });

    function showTXStatus(msg, isError) {
        var el = document.getElementById('tx-status');
        el.innerHTML = '<span class="' + (isError ? 'tx-err' : 'tx-ok') + '">' + escHtml(msg) + '</span>';
        setTimeout(function() { el.innerHTML = ''; }, 5000);
    }

    // ── APRS Messages ──
    var lastMsgCount = 0;

    function updateAPRSMessages() {
        var list = document.getElementById('aprs-msg-list');
        var countEl = document.getElementById('aprs-msg-count');
        if (!list) return;

        // Get configured callsign for highlighting
        var myCall = (document.getElementById('tx-callsign').value || '').toUpperCase().trim();

        countEl.textContent = aprsMessages.length;

        // Show newest first
        var msgs = aprsMessages.slice().reverse();
        var html = '';
        msgs.forEach(function(m) {
            var isIncoming = myCall && m.to.toUpperCase() === myCall;
            var isOutgoing = myCall && m.from.toUpperCase() === myCall;
            var cls = isIncoming ? 'msg-in' : (isOutgoing ? 'msg-out' : '');
            var time = new Date(m.time * 1000).toLocaleTimeString();
            html += '<div class="aprs-msg-item ' + cls + '">' +
                '<span class="aprs-msg-time">' + time + '</span>' +
                '<span class="aprs-msg-from">' + escHtml(m.from) + '</span>' +
                ' <span class="aprs-msg-to">&rarr; ' + escHtml(m.to) + '</span>' +
                '<div class="aprs-msg-text">' + escHtml(m.text) + '</div>' +
                '</div>';
        });

        if (msgs.length === 0) {
            html = '<div style="padding:12px 8px;color:#475569;font-size:11px;text-align:center">No messages yet</div>';
        }

        list.innerHTML = html;

        // Scroll to top (newest) if new messages arrived
        if (aprsMessages.length > lastMsgCount) {
            list.scrollTop = 0;
        }
        lastMsgCount = aprsMessages.length;
    }

    // ── Offline Map Download ──
    var dlActive = false;
    var dlBounds = null;        // L.LatLngBounds from user selection
    var dlRect = null;          // L.Rectangle shown on map
    var dlSelecting = false;    // true while in selection mode
    var dlDragStart = null;     // L.LatLng where mousedown started

    function lon2tile(lon, z) { return Math.floor((lon + 180) / 360 * Math.pow(2, z)); }
    function lat2tile(lat, z) { var r = lat * Math.PI / 180; return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, z)); }

    function getTileList(bounds, minZ, maxZ) {
        var tiles = [];
        for (var z = minZ; z <= maxZ; z++) {
            var x1 = lon2tile(bounds.getWest(), z);
            var x2 = lon2tile(bounds.getEast(), z);
            var y1 = lat2tile(bounds.getNorth(), z);
            var y2 = lat2tile(bounds.getSouth(), z);
            for (var x = x1; x <= x2; x++) {
                for (var y = y1; y <= y2; y++) {
                    tiles.push({ z: z, x: x, y: y });
                }
            }
        }
        return tiles;
    }

    function updateDLEstimate() {
        if (!dlBounds) return;
        var minZ = parseInt(document.getElementById('dl-min-zoom').value);
        var maxZ = parseInt(document.getElementById('dl-max-zoom').value);
        if (maxZ < minZ) { maxZ = minZ; document.getElementById('dl-max-zoom').value = maxZ; }
        document.getElementById('dl-min-zoom-val').textContent = minZ;
        document.getElementById('dl-max-zoom-val').textContent = maxZ;
        var tiles = getTileList(dlBounds, minZ, maxZ);
        var count = tiles.length;
        document.getElementById('dl-tile-count').textContent = count.toLocaleString();
        var mb = (count * 15) / 1024;
        document.getElementById('dl-est-size').textContent = mb < 1 ? mb.toFixed(1) + ' MB' : Math.round(mb) + ' MB';
    }

    function updateCacheInfo() {
        countCachedTiles().then(function(n) {
            var el = document.getElementById('dl-cache-info');
            if (el) el.textContent = n > 0 ? n.toLocaleString() + ' tiles cached' : 'No cached tiles';
        });
    }

    function showDLArea() {
        document.getElementById('dl-no-area').classList.add('hidden');
        document.getElementById('dl-has-area').classList.remove('hidden');
        var b = dlBounds;
        document.getElementById('dl-area-desc').textContent =
            b.getNorth().toFixed(3) + ', ' + b.getWest().toFixed(3) +
            '  to  ' + b.getSouth().toFixed(3) + ', ' + b.getEast().toFixed(3);
        updateDLEstimate();
    }

    function clearDLArea() {
        dlBounds = null;
        if (dlRect) { map.removeLayer(dlRect); dlRect = null; }
        document.getElementById('dl-no-area').classList.remove('hidden');
        document.getElementById('dl-has-area').classList.add('hidden');
    }

    // ── Selection mode: user draws a rectangle on the map ──
    function enterSelectMode() {
        closeSetup();
        dlSelecting = true;
        if (dlRect) { map.removeLayer(dlRect); dlRect = null; }
        map.dragging.disable();
        map.getContainer().classList.add('map-selecting');
        document.getElementById('dl-select-banner').classList.add('visible');
    }

    function exitSelectMode() {
        dlSelecting = false;
        dlDragStart = null;
        map.dragging.enable();
        map.getContainer().classList.remove('map-selecting');
        document.getElementById('dl-select-banner').classList.remove('visible');
    }

    map.on('mousedown', function(e) {
        if (!dlSelecting) return;
        dlDragStart = e.latlng;
        if (dlRect) { map.removeLayer(dlRect); dlRect = null; }
        // Create initial rectangle
        dlRect = L.rectangle([dlDragStart, dlDragStart], {
            color: '#38bdf8', weight: 2, fillOpacity: 0.15, dashArray: '6 4'
        }).addTo(map);
    });

    map.on('mousemove', function(e) {
        if (!dlSelecting || !dlDragStart || !dlRect) return;
        dlRect.setBounds(L.latLngBounds(dlDragStart, e.latlng));
    });

    map.on('mouseup', function(e) {
        if (!dlSelecting || !dlDragStart) return;
        dlBounds = L.latLngBounds(dlDragStart, e.latlng);
        // Require a minimum drag distance (not just a click)
        var p1 = map.latLngToContainerPoint(dlBounds.getNorthWest());
        var p2 = map.latLngToContainerPoint(dlBounds.getSouthEast());
        if (Math.abs(p2.x - p1.x) < 20 || Math.abs(p2.y - p1.y) < 20) {
            if (dlRect) { map.removeLayer(dlRect); dlRect = null; }
            dlBounds = null;
            return; // too small, ignore
        }
        // Finalize rectangle style
        dlRect.setStyle({ dashArray: null, fillOpacity: 0.1 });
        exitSelectMode();
        // Reopen settings with area selected
        openSetup();
        showDLArea();
    });

    // Escape to cancel selection
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && dlSelecting) {
            if (dlRect) { map.removeLayer(dlRect); dlRect = null; }
            exitSelectMode();
        }
    });

    // ── Button handlers ──
    if (document.getElementById('dl-select-area')) {
        document.getElementById('dl-select-area').addEventListener('click', enterSelectMode);
    }
    if (document.getElementById('dl-reselect')) {
        document.getElementById('dl-reselect').addEventListener('click', function() {
            clearDLArea();
            enterSelectMode();
        });
    }

    var dlMinZoom = document.getElementById('dl-min-zoom');
    var dlMaxZoom = document.getElementById('dl-max-zoom');
    if (dlMinZoom) {
        dlMinZoom.addEventListener('input', updateDLEstimate);
        dlMaxZoom.addEventListener('input', updateDLEstimate);
    }

    if (document.getElementById('dl-start')) {
        document.getElementById('dl-start').addEventListener('click', function() {
            if (dlActive || !dlBounds) return;
            var minZ = parseInt(document.getElementById('dl-min-zoom').value);
            var maxZ = parseInt(document.getElementById('dl-max-zoom').value);
            var tiles = getTileList(dlBounds, minZ, maxZ);
            if (tiles.length === 0) return;
            if (tiles.length > 50000 && !confirm('This will download ' + tiles.length.toLocaleString() + ' tiles. Continue?')) return;

            dlActive = true;
            var btn = document.getElementById('dl-start');
            btn.textContent = 'Downloading...';
            btn.classList.remove('start');
            btn.classList.add('stop');
            document.getElementById('dl-progress').classList.remove('hidden');
            var fill = document.getElementById('dl-progress-fill');
            var txt = document.getElementById('dl-progress-text');
            var done = 0;
            var failed = 0;
            var total = tiles.length;

            function updateProgress() {
                var pct = Math.round((done + failed) / total * 100);
                fill.style.width = pct + '%';
                txt.textContent = done + ' / ' + total + (failed > 0 ? ' (' + failed + ' failed)' : '');
            }

            var idx = 0;
            function next() {
                if (idx >= total) {
                    if (done + failed >= total) {
                        dlActive = false;
                        btn.textContent = 'Download Tiles';
                        btn.classList.remove('stop');
                        btn.classList.add('start');
                        txt.textContent = 'Done! ' + done + ' tiles cached' + (failed > 0 ? ', ' + failed + ' failed' : '');
                        updateCacheInfo();
                    }
                    return;
                }
                var t = tiles[idx++];
                var style = MAP_STYLES[currentStyle];
                var subs = style.subdomains ? style.subdomains.split('') : [''];
                var s = subs[(t.x + t.y) % subs.length];
                var url = TILE_URL.replace('{s}', s).replace('{z}', t.z).replace('{x}', t.x).replace('{y}', t.y).replace('{r}', '');
                var key = currentStyle + '/' + t.z + '/' + t.x + '/' + t.y;

                getTile(key).then(function(existing) {
                    if (existing) {
                        done++;
                        updateProgress();
                        next();
                        return;
                    }
                    fetch(url).then(function(r) {
                        if (!r.ok) throw new Error(r.status);
                        return r.blob();
                    }).then(function(blob) {
                        return putTile(key, blob);
                    }).then(function() {
                        done++;
                        updateProgress();
                        next();
                    }).catch(function() {
                        failed++;
                        updateProgress();
                        next();
                    });
                });
            }

            updateProgress();
            for (var c = 0; c < 6; c++) next();
        });

        document.getElementById('dl-clear').addEventListener('click', function() {
            if (dlActive) return;
            if (!confirm('Clear all cached map tiles?')) return;
            clearTileCache().then(function() {
                updateCacheInfo();
                var ptxt = document.getElementById('dl-progress-text');
                var pfill = document.getElementById('dl-progress-fill');
                if (ptxt) ptxt.textContent = '';
                if (pfill) pfill.style.width = '0%';
            });
        });
    }

    // ── Map style switcher ──
    var styleGrid = document.getElementById('map-style-grid');
    if (styleGrid) {
        styleGrid.addEventListener('click', function(e) {
            var btn = e.target.closest('.map-style-btn');
            if (!btn) return;
            var styleId = btn.getAttribute('data-style');
            if (styleId && MAP_STYLES[styleId]) {
                applyMapStyle(styleId);
            }
        });
    }

    // Update cache info when setup opens
    var origOpenSetupForDL = openSetup;
    openSetup = function() {
        origOpenSetupForDL();
        updateCacheInfo();
        if (dlBounds) showDLArea();
        loadAPIKeyStatus();
    };

    // ── API Keys ──
    function loadAPIKeyStatus() {
        fetch('/api/config/keys')
            .then(function(r) { return r.json(); })
            .then(function(keys) {
                var input = document.getElementById('aisstream-key');
                if (input) {
                    if (keys.aisstream) {
                        input.placeholder = '••••••• (saved)';
                        input.value = '';
                    } else {
                        input.placeholder = 'API key for online AIS feed';
                    }
                }
            }).catch(function() {});
    }

    var aisKeyBtn = document.getElementById('aisstream-save');
    if (aisKeyBtn) {
        aisKeyBtn.addEventListener('click', function() {
            var input = document.getElementById('aisstream-key');
            var status = document.getElementById('api-keys-status');
            var key = (input.value || '').trim();
            if (!key) {
                status.textContent = 'Enter a key first';
                status.style.color = '#fca5a5';
                return;
            }
            fetch('/api/config/keys', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: 'aisstream', key: key })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) {
                    status.textContent = 'Error: ' + data.error;
                    status.style.color = '#fca5a5';
                } else {
                    status.textContent = 'AISStream key saved';
                    status.style.color = '#6ee7b7';
                    input.value = '';
                    input.placeholder = '••••••• (saved)';
                    setTimeout(function() { status.textContent = ''; }, 4000);
                }
            })
            .catch(function() {
                status.textContent = 'Save failed';
                status.style.color = '#fca5a5';
            });
        });
    }

    // ── Alert zones ──
    var alertZones = [];
    var alertZoneLayer = L.layerGroup().addTo(map);
    var seenAlertEventIds = new Set();
    var alertAddState = null; // { lat, lon } once user clicks the map

    function handleAlertZonesPayload(zones) {
        alertZones = zones || [];
        renderAlertZonesList();
        renderAlertZonesOnMap();
    }

    function handleAlertEventsPayload(events) {
        (events || []).forEach(function(ev) {
            if (seenAlertEventIds.has(ev.id)) return;
            seenAlertEventIds.add(ev.id);
            // First connection: don't toast historical events.
            if (seenAlertEventIds.size === (events || []).length) {
                return;
            }
            showAlertToast(ev);
        });
    }

    function renderAlertZonesOnMap() {
        alertZoneLayer.clearLayers();
        alertZones.forEach(function(z) {
            var circle = L.circle([z.lat, z.lon], {
                radius: z.radius_km * 1000,
                color: '#f59e0b', weight: 1.5,
                fillColor: '#f59e0b', fillOpacity: 0.08,
            }).bindTooltip(z.name + ' — ' + z.radius_km + ' km' +
                ((z.category_filters && z.category_filters.length)
                    ? ' (' + z.category_filters.join('/') + ')'
                    : (z.category_filter ? ' (' + z.category_filter + ')' : '')));
            alertZoneLayer.addLayer(circle);
        });
    }

    function renderAlertZonesList() {
        var el = document.getElementById('alert-zones-list');
        if (!el) return;
        if (!alertZones.length) {
            el.innerHTML = '<div style="color:#64748b">No zones. Click + Add to create one.</div>';
            return;
        }
        el.innerHTML = alertZones.map(function(z) {
            var cats = (z.category_filters && z.category_filters.length)
                ? z.category_filters.join(' / ')
                : (z.category_filter || 'any');
            var label = cats + (z.callsign_filter ? ' · ' + z.callsign_filter : '');
            return '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #1e293b">' +
                '<div style="flex:1;min-width:0">' +
                    '<div style="color:#e0e6ed;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(z.name) + '</div>' +
                    '<div style="font-size:10px;color:#64748b">' + z.radius_km + ' km · ' + escHtml(label) + '</div>' +
                '</div>' +
                '<button data-zone-id="' + z.id + '" class="alert-zone-del tx-btn-sm" style="margin-left:6px">×</button>' +
            '</div>';
        }).join('');
        el.querySelectorAll('.alert-zone-del').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var id = btn.getAttribute('data-zone-id');
                fetch('/api/alerts/zones/' + id, { method: 'DELETE' }).then(loadAlertZones);
            });
        });
    }

    function loadAlertZones() {
        fetch('/api/alerts/zones').then(function(r) { return r.json(); })
            .then(function(zones) { handleAlertZonesPayload(zones); }).catch(function() {});
    }

    function showAlertToast(ev) {
        var box = document.getElementById('alert-toast-stack');
        if (!box) {
            box = document.createElement('div');
            box.id = 'alert-toast-stack';
            box.style.cssText = 'position:fixed;top:60px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:6px;max-width:340px';
            document.body.appendChild(box);
        }
        var when = new Date(ev.timestamp * 1000).toLocaleTimeString();
        var card = document.createElement('div');
        card.style.cssText = 'background:#0f172a;border:1px solid #f59e0b;border-left:4px solid #f59e0b;border-radius:6px;padding:10px 12px;color:#e0e6ed;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);cursor:pointer';
        card.innerHTML = '<div style="font-weight:600;color:#fbbf24;margin-bottom:2px">⚠ Zone alert: ' + escHtml(ev.zone_name) + '</div>' +
            '<div>' + escHtml(ev.callsign || ev.target_id) + ' (' + escHtml(ev.target_type) + ')</div>' +
            '<div style="color:#94a3b8;font-size:11px;margin-top:2px">' + when + '</div>';
        card.addEventListener('click', function() {
            window.skywatch.select(ev.target_id);
            box.removeChild(card);
        });
        box.appendChild(card);
        setTimeout(function() { try { box.removeChild(card); } catch(e) {} }, 12000);
        try {
            var beep = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=');
            beep.play().catch(function() {});
        } catch(e) {}
    }

    function wireAlertControls() {
        var addBtn = document.getElementById('alert-add-btn');
        var panel = document.getElementById('alert-add-panel');
        var saveBtn = document.getElementById('alert-save');
        var cancelBtn = document.getElementById('alert-cancel');
        if (!addBtn || !panel) return;

        var pickHandler = null;
        var pickMarker = null;

        function startPicking() {
            panel.style.display = 'block';
            saveBtn.disabled = true;
            alertAddState = null;
            map.getContainer().style.cursor = 'crosshair';
            pickHandler = function(e) {
                alertAddState = { lat: e.latlng.lat, lon: e.latlng.lng };
                if (pickMarker) alertZoneLayer.removeLayer(pickMarker);
                pickMarker = L.circleMarker(e.latlng, { radius: 6, color: '#f59e0b', fillColor: '#f59e0b', fillOpacity: 0.6 });
                alertZoneLayer.addLayer(pickMarker);
                saveBtn.disabled = false;
            };
            map.on('click', pickHandler);
        }

        function stopPicking() {
            panel.style.display = 'none';
            map.getContainer().style.cursor = '';
            if (pickHandler) { map.off('click', pickHandler); pickHandler = null; }
            if (pickMarker) { alertZoneLayer.removeLayer(pickMarker); pickMarker = null; }
            alertAddState = null;
            document.getElementById('alert-name').value = '';
            document.getElementById('alert-callsign').value = '';
            document.getElementById('alert-radius').value = '5';
            document.querySelectorAll('#alert-category-group .alert-cat').forEach(function(c) { c.checked = false; });
        }

        addBtn.addEventListener('click', startPicking);
        cancelBtn.addEventListener('click', stopPicking);
        saveBtn.addEventListener('click', function() {
            if (!alertAddState) return;
            var cats = Array.prototype.slice
                .call(document.querySelectorAll('#alert-category-group .alert-cat:checked'))
                .map(function(el) { return el.value; });
            var body = {
                name: document.getElementById('alert-name').value || ('Zone ' + (alertZones.length + 1)),
                lat: alertAddState.lat,
                lon: alertAddState.lon,
                radius_km: parseFloat(document.getElementById('alert-radius').value) || 5.0,
                target_types: ['aircraft'],
                category_filters: cats,
                callsign_filter: document.getElementById('alert-callsign').value || '',
            };
            fetch('/api/alerts/zones', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            }).then(function(r) { return r.json(); }).then(function() {
                stopPicking();
                loadAlertZones();
            });
        });
    }

    wireAlertControls();
    loadAlertZones();

    // ── Public API ──
    window.skywatch.select = selectTarget;

    // ── Start ──
    connect();

})();
