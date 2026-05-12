const ProximaWebSocketLib = {
    $sockets: {
        nextId: 0,
        sockets: {}
    },
    ProximaWebSocketCreate: function(url, protocol, openCb, closeCb, messageCb) {
        const id = sockets.nextId++;
        const ws = new WebSocket(UTF8ToString(url), UTF8ToString(protocol));
        ws.onopen = function() { Module.dynCall_vi(openCb, id) };
        ws.onclose = function() { Module.dynCall_vi(closeCb, id) };
        ws.onmessage = function(e) {
            const bufferSize = lengthBytesUTF8(e.data) + 1;
            const buffer = _malloc(bufferSize);
            stringToUTF8(e.data, buffer, bufferSize);

            try {
                Module.dynCall_vii(messageCb, id, buffer);
            } finally {
                _free(buffer);
            }
        };

        sockets.sockets[id] = ws;
        return id;
    },
    ProximaWebSocketSend: function(id, data) {
        sockets.sockets[id].send(UTF8ToString(data));
    },
    ProximaWebSocketDestroy: function(id) {
        sockets.sockets[id].close();
        delete sockets.sockets[id];
    },
}

autoAddDeps(ProximaWebSocketLib, '$sockets');
mergeInto(LibraryManager.library, ProximaWebSocketLib);