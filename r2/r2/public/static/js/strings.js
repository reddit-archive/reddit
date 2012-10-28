r.strings = function(name, params) {
    var string = r.strings.index[name]
    if (params) {
        return r.utils.pyStrFormat(string, params)
    } else {
        return string
    }
}

r.strings.index = {}
r.strings.set = function(strings) {
    _.extend(r.strings.index, strings)
    this.permissions = this.index.permissions
}
