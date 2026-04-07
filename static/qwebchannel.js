// Copyright (C) 2016 The Qt Company Ltd.
// SPDX-License-Identifier: LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
"use strict";

var QWebChannelMessageTypes = {
    signal: 1, propertyUpdate: 2, init: 3, idle: 4, debug: 5,
    invokeMethod: 6, connectToSignal: 7, disconnectFromSignal: 8,
    setProperty: 9, response: 10,
};

var QWebChannel = function(transport, initCallback, converters) {
    if (typeof transport !== "object" || typeof transport.send !== "function") {
        console.error("The QWebChannel expects a transport object with a send function.");
        return;
    }
    var channel = this;
    this.transport = transport;
    this.usedConverters = [];
    this.send = function(data) {
        if (typeof(data) !== "string") data = JSON.stringify(data);
        channel.transport.send(data);
    };
    this.transport.onmessage = function(message) {
        var data = message.data;
        if (typeof data === "string") data = JSON.parse(data);
        switch (data.type) {
            case QWebChannelMessageTypes.signal: channel.handleSignal(data); break;
            case QWebChannelMessageTypes.response: channel.handleResponse(data); break;
            case QWebChannelMessageTypes.propertyUpdate: channel.handlePropertyUpdate(data); break;
            default: console.error("invalid message received:", message.data); break;
        }
    };
    this.execCallbacks = {};
    this.execId = 0;
    this.exec = function(data, callback) {
        if (!callback) { channel.send(data); return; }
        if (channel.execId === Number.MAX_VALUE) channel.execId = Number.MIN_VALUE;
        if (data.hasOwnProperty("id")) { console.error("Cannot exec message with property id"); return; }
        data.id = channel.execId++;
        channel.execCallbacks[data.id] = callback;
        channel.send(data);
    };
    this.objects = {};
    this.handleSignal = function(message) {
        var object = channel.objects[message.object];
        if (object) object.signalEmitted(message.signal, message.args);
        else console.warn("Unhandled signal: " + message.object + "::" + message.signal);
    };
    this.handleResponse = function(message) {
        if (!message.hasOwnProperty("id")) { console.error("Invalid response"); return; }
        channel.execCallbacks[message.id](message.data);
        delete channel.execCallbacks[message.id];
    };
    this.handlePropertyUpdate = function(message) {
        message.data.forEach(data => {
            var object = channel.objects[data.object];
            if (object) object.propertyUpdate(data.signals, data.properties);
            else console.warn("Unhandled property update");
        });
        channel.exec({type: QWebChannelMessageTypes.idle});
    };
    channel.exec({type: QWebChannelMessageTypes.init}, function(data) {
        for (const objectName of Object.keys(data)) {
            new QObject(objectName, data[objectName], channel);
        }
        for (const objectName of Object.keys(channel.objects)) {
            channel.objects[objectName].unwrapProperties();
        }
        if (initCallback) initCallback(channel);
        channel.exec({type: QWebChannelMessageTypes.idle});
    });
};

function QObject(name, data, webChannel) {
    this.__id__ = name;
    webChannel.objects[name] = this;
    this.__objectSignals__ = {};
    this.__propertyCache__ = {};
    var object = this;
    this.unwrapQObject = function(response) {
        if (response instanceof Array) return response.map(qobj => object.unwrapQObject(qobj));
        if (!(response instanceof Object)) return response;
        if (!response["__QObject*__"] || response.id === undefined) {
            var jObj = {};
            for (const propName of Object.keys(response)) jObj[propName] = object.unwrapQObject(response[propName]);
            return jObj;
        }
        var objectId = response.id;
        if (webChannel.objects[objectId]) return webChannel.objects[objectId];
        if (!response.data) { console.error("Cannot unwrap unknown QObject " + objectId); return; }
        var qObject = new QObject(objectId, response.data, webChannel);
        qObject.destroyed.connect(function() {
            if (webChannel.objects[objectId] === qObject) {
                delete webChannel.objects[objectId];
                Object.keys(qObject).forEach(n => delete qObject[n]);
            }
        });
        qObject.unwrapProperties();
        return qObject;
    };
    this.unwrapProperties = function() {
        for (const propertyIdx of Object.keys(object.__propertyCache__)) {
            object.__propertyCache__[propertyIdx] = object.unwrapQObject(object.__propertyCache__[propertyIdx]);
        }
    };
    function addSignal(signalData, isPropertyNotifySignal) {
        var signalName = signalData[0], signalIndex = signalData[1];
        object[signalName] = {
            connect: function(callback) {
                if (typeof(callback) !== "function") { console.error("Bad callback"); return; }
                object.__objectSignals__[signalIndex] = object.__objectSignals__[signalIndex] || [];
                object.__objectSignals__[signalIndex].push(callback);
                if (isPropertyNotifySignal) return;
                if (signalName === "destroyed" || signalName === "destroyed()" || signalName === "destroyed(QObject*)") return;
                if (object.__objectSignals__[signalIndex].length == 1) {
                    webChannel.exec({type: QWebChannelMessageTypes.connectToSignal, object: object.__id__, signal: signalIndex});
                }
            },
            disconnect: function(callback) {
                if (typeof(callback) !== "function") { console.error("Bad callback"); return; }
                object.__objectSignals__[signalIndex] = (object.__objectSignals__[signalIndex] || []).filter(function(c) { return c != callback; });
                if (!isPropertyNotifySignal && object.__objectSignals__[signalIndex].length === 0) {
                    webChannel.exec({type: QWebChannelMessageTypes.disconnectFromSignal, object: object.__id__, signal: signalIndex});
                }
            }
        };
    }
    function invokeSignalCallbacks(signalName, signalArgs) {
        var connections = object.__objectSignals__[signalName];
        if (connections) connections.forEach(function(callback) { callback.apply(callback, signalArgs); });
    }
    this.propertyUpdate = function(signals, propertyMap) {
        for (const propertyIndex of Object.keys(propertyMap)) {
            object.__propertyCache__[propertyIndex] = this.unwrapQObject(propertyMap[propertyIndex]);
        }
        for (const signalName of Object.keys(signals)) invokeSignalCallbacks(signalName, signals[signalName]);
    };
    this.signalEmitted = function(signalName, signalArgs) {
        invokeSignalCallbacks(signalName, this.unwrapQObject(signalArgs));
    };
    function addMethod(methodData) {
        var methodName = methodData[0], methodIdx = methodData[1];
        var invokedMethod = methodName[methodName.length - 1] === ')' ? methodIdx : methodName;
        object[methodName] = function() {
            var args = [], callback;
            for (var i = 0; i < arguments.length; ++i) {
                if (typeof arguments[i] === "function") callback = arguments[i];
                else args.push(arguments[i]);
            }
            var result;
            if (!callback && (typeof(Promise) === 'function')) {
                result = new Promise(function(resolve, reject) { callback = resolve; });
            }
            webChannel.exec({"type": QWebChannelMessageTypes.invokeMethod, "object": object.__id__, "method": invokedMethod, "args": args}, function(response) {
                if (response !== undefined && callback) callback(object.unwrapQObject(response));
            });
            return result;
        };
    }
    function bindGetterSetter(propertyInfo) {
        var propertyIndex = propertyInfo[0], propertyName = propertyInfo[1];
        var notifySignalData = propertyInfo[2];
        object.__propertyCache__[propertyIndex] = propertyInfo[3];
        if (notifySignalData) {
            if (notifySignalData[0] === 1) notifySignalData[0] = propertyName + "Changed";
            addSignal(notifySignalData, true);
        }
        Object.defineProperty(object, propertyName, {
            configurable: true,
            get: function() { return object.__propertyCache__[propertyIndex]; },
            set: function(value) {
                if (value === undefined) { console.warn("Property setter called with undefined value"); return; }
                object.__propertyCache__[propertyIndex] = value;
                webChannel.exec({"type": QWebChannelMessageTypes.setProperty, "object": object.__id__, "property": propertyIndex, "value": value});
            }
        });
    }
    data.methods.forEach(addMethod);
    data.properties.forEach(bindGetterSetter);
    data.signals.forEach(function(signal) { addSignal(signal, false); });
    Object.assign(object, data.enums);
}

QObject.prototype.toJSON = function() {
    if (this.__id__ === undefined) return {};
    return { id: this.__id__, "__QObject*__": true };
};

if (typeof module === 'object') {
    module.exports = { QWebChannel: QWebChannel };
}
