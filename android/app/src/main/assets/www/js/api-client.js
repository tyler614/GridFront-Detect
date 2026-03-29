/* ═══════════════════════════════════════════════════════════
   GridFront Detect — API Client
   Talks to the Flask backend via the LocalAssetServer proxy.
   All /api/* calls go through the same origin (port 8080)
   and are forwarded to Flask on port 5555.
   ═══════════════════════════════════════════════════════════ */

window.GF = window.GF || {};

GF.api = {
    baseUrl: '',  // Same origin — proxied through LocalAssetServer

    async get(path) {
        var res = await fetch(this.baseUrl + path);
        if (!res.ok) throw new Error('API ' + res.status + ': ' + path);
        return res.json();
    },

    async post(path, data) {
        var res = await fetch(this.baseUrl + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: data !== undefined ? JSON.stringify(data) : undefined,
        });
        if (!res.ok) throw new Error('API ' + res.status + ': ' + path);
        return res.json();
    },

    async patch(path, data) {
        var res = await fetch(this.baseUrl + path, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: data !== undefined ? JSON.stringify(data) : undefined,
        });
        if (!res.ok) throw new Error('API ' + res.status + ': ' + path);
        return res.json();
    },

    async del(path) {
        var res = await fetch(this.baseUrl + path, { method: 'DELETE' });
        if (!res.ok) throw new Error('API ' + res.status + ': ' + path);
        return res.json();
    },

    // ── Convenience methods ─────────────────────────────────
    getSpatial:         function() { return this.get('/api/spatial'); },
    getConfig:          function() { return this.get('/api/config'); },
    getMachines:        function() { return this.get('/api/machines'); },
    getHealth:          function() { return this.get('/api/system/health'); },
    getDetectionConfig: function() { return this.get('/api/detection/config'); },
    activateMachine:    function(type) { return this.post('/api/machines/' + type + '/activate'); },

    // ── SSE stream for real-time detection data ─────────────
    connectStream: function(onData, onError) {
        var source = new EventSource('/api/spatial/stream');
        source.onmessage = function(event) {
            try {
                onData(JSON.parse(event.data));
            } catch (e) {
                console.warn('Stream parse error:', e);
            }
        };
        source.onerror = function(e) {
            if (onError) onError(e);
        };
        return source;  // Caller can call source.close() to disconnect
    },

    // ── Connection status ───────────────────────────────────
    _connected: false,

    async checkConnection() {
        try {
            await this.getHealth();
            this._connected = true;
        } catch (e) {
            this._connected = false;
        }
        return this._connected;
    },

    isConnected: function() {
        return this._connected;
    },
};
