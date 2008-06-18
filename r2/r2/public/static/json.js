if (!Object.prototype.toJSONString) {
    Array.prototype.toJSONString = function (w) {
        var a = [],     // The array holding the partial texts.
            i,          // Loop counter.
            l = this.length,
            v;          // The value to be stringified.
        for (i = 0; i < l; i += 1) {
            v = this[i];
            switch (typeof v) {
            case 'object':
                if (v) {
                    if (typeof v.toJSONString === 'function') {
                        a.push(v.toJSONString(w));
                    }
                } else {
                    a.push('null');
                }
                break;
            case 'string':
            case 'number':
            case 'boolean':
                a.push(v.toJSONString());
            }
        }
        return '[' + a.join(',') + ']';
    };
    Boolean.prototype.toJSONString = function () {
        return String(this);
    };
    Date.prototype.toJSONString = function () {
        function f(n) {
            return n < 10 ? '0' + n : n;
        }
        return '"' + this.getUTCFullYear() + '-' +
                f(this.getUTCMonth() + 1)  + '-' +
                f(this.getUTCDate())       + 'T' +
                f(this.getUTCHours())      + ':' +
                f(this.getUTCMinutes())    + ':' +
                f(this.getUTCSeconds())    + 'Z"';
    };
    Number.prototype.toJSONString = function () {
        return isFinite(this) ? String(this) : 'null';
    };
    Object.prototype.toJSONString = function (w) {
        var a = [],     
            k,          
            i,          
            v;          
        if (w) {
            for (i = 0; i < w.length; i += 1) {
                k = w[i];
                if (typeof k === 'string') {
                    v = this[k];
                    switch (typeof v) {
                    case 'object':
                        if (v) {
                            if (typeof v.toJSONString === 'function') {
                                a.push(k.toJSONString() + ':' +
                                       v.toJSONString(w));
                            }
                        } else {
                            a.push(k.toJSONString() + ':null');
                        }
                        break;
                    case 'string':
                    case 'number':
                    case 'boolean':
                        a.push(k.toJSONString() + ':' + v.toJSONString());
                    }
                }
            }
        } else {
            for (k in this) {
                if (typeof k === 'string' &&
                        Object.prototype.hasOwnProperty.apply(this, [k])) {
                    v = this[k];
                    switch (typeof v) {
                    case 'object':
                        if (v) {
                            if (typeof v.toJSONString === 'function') {
                                a.push(k.toJSONString() + ':' +
                                       v.toJSONString());
                            }
                        } else {
                            a.push(k.toJSONString() + ':null');
                        }
                        break;
                    case 'string':
                    case 'number':
                    case 'boolean':
                        a.push(k.toJSONString() + ':' + v.toJSONString());
                    }
                }
            }
        }
        return '{' + a.join(',') + '}';
    };
    (function (s) {
        var m = {
            '\b': '\\b',
            '\t': '\\t',
            '\n': '\\n',
            '\f': '\\f',
            '\r': '\\r',
            '"' : '\\"',
            '\\': '\\\\'
        };
        s.parseJSON = function (filter) {
            var j;
            function walk(k, v) {
                var i;
                if (v && typeof v === 'object') {
                    for (i in v) {
                        if (Object.prototype.hasOwnProperty.apply(v, [i])) {
                            v[i] = walk(i, v[i]);
                        }
                    }
                }
                return filter(k, v);
            }
            if (/^[,:{}\[\]0-9.\-+Eaeflnr-u \n\r\t]*$/.test(this.
                    replace(/\\./g, '@').
                    replace(/"[^"\\\n\r]*"/g, ''))) {
                j = eval('(' + this + ')');
                return typeof filter === 'function' ? walk('', j) : j;
            }
            throw new SyntaxError('parseJSON');
        };
        s.toJSONString = function () {
            if (/["\\\x00-\x1f]/.test(this)) {
                return '"' + this.replace(/[\x00-\x1f\\"]/g, function (a) {
                    var c = m[a];
                    if (c) {
                        return c;
                    }
                    c = a.charCodeAt();
                    return '\\u00' +
                        Math.floor(c / 16).toString(16) +
                        (c % 16).toString(16);
                }) + '"';
            }
            return '"' + this + '"';
        };
    })(String.prototype);
}
