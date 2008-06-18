
function UserTable(name) {
    this.table = $(name);
    this.header = $(name+"_header");
};


UserTable.prototype  = {
    _del_row: function(name) {
        var row = this.table.rows.namedItem(name);
        if(row) {
            this.table.deleteRow(row.rowIndex);
        }
    },
    
    _new_row: function(name, cellinnards, pos) {
        if(!pos) { pos = 0; }
        var row = this.table.insertRow(pos);
        hide(row);
        row.id = name;
        if(row) {
            for(var i = 0; i < cellinnards.length; i++) {
                var cell = row.insertCell(row.cells.length);
                cell.innerHTML = unsafe(cellinnards[i]);
            }
        }
        show(row);
    }
};

UserTable.findTable = function(rowname) {
    var row = $(rowname);
    var ut = new UserTable(row.parentNode.parentNode.id);
    return ut;
};

UserTable.getUser = function(name) {
    return name.split('_')[1];
}

UserTable.add = function(r) {
    var table = new UserTable(r.id);
    table._new_row(r.name, r.cells);
    show(table.header);
    return false;
};


UserTable.delRow = function(name) {
    var table = UserTable.findTable(name);
    table._del_row(name);
    if (table.table.rows.length == 0) {
        hide(table.header);
    }
    return table;
};


UserTable.del = function(type, container_name) {
    var f = function(name, uh) {
        var table = UserTable.delRow(name);
        redditRequest("friend", {name: UserTable.getUser(name),
                    action: 'remove', container: container_name,
                    type: type, uh: uh});
    };
    return f;
};

class_dict["UserTable"] = UserTable;

