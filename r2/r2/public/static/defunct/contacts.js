//stuff that needs to be moved
function rowon(el) {el.className = "menu collapse d";}
function rowoff(el) {el.className = "menu collapse r";}

function helpon() {
    show("markhelp");
    $("marklink").href = "javascript: helpoff()";
    $("marklink").blur();
    rowon($("marktoggle"));
}

function helpoff() {
    hide("markhelp");
    $("marklink").href = "javascript: helpon()";
    $("marklink").blur();
    rowoff($("marktoggle"));
}

//function shareon() {
//    show("share");
//    $("sharelink").href = "javascript: shareoff()";
//    $("sharelink").blur();
//    rowon($("sharetoggle"));    
//}

//function shareoff() {
//    hide("share");
//    $("sharelink").href = "javascript: shareon()";
//    $("sharelink").blur();
//    rowoff($("sharetoggle"));    
//}


function list_toggle_on(form, name, func) {
  id = _id(form);
  show(name + id);
  rowon($(name+"toggle_"+id));
  $(name+"link_"+id).onclick = function(event) { func(this); };
  $(name+"link_"+id).blur();
}

function list_toggle_off(form, name, func) {
  id = _id(form);
  hide(name+id);
  rowoff($(name+"toggle_"+id));
  $(name+"link_"+id).onclick = function(event) { func(this); };
  $(name+"link_"+id).blur();
}


function contactson(form) {
  list_toggle_on(form, 'contacts_', contactsoff);
}

function contactsoff(form) {
  list_toggle_off(form, 'contacts_', contactson);
}


var contable = new ConTable("contactlst",
                            function (name, val) {new Ajax.Request('/ajax', {parameters: "action=ualias&name="+name+"&val="+val});},
                            function (name) {new Ajax.Request('/ajax', {parameters: "action=ualias&name="+name})},
                            function (name) {
                                if ($("to").value.length > 0) $("to").value += ", " + name;
                                else $("to").value = name;
                            });

function makeedit(row) {
    var text = new Array("alias", "emails/aliases");
    for (var i = 1; i < 3; i++) {
        var c = row.cells[i];
        var empty = c.innerHTML;
        c.innerHTML = "<input type='text' "
            + (empty.length > 0 ? "" : "style='color:gray' onfocus='clearTitle(this)'")
            + " value='" + (empty || text[i-1]) + "'/>";
    }
    row.cells[3].innerHTML = "<a href='javascript:return true;' onclick='saverow(this); return false;'>save</a>";
}

function makefinal(row) {
    for (var i = 1; i < 3; i++) {
        var c = row.cells[i];
        c.innerHTML = c.firstChild && c.firstChild.value || "";
    }
    row.cells[3].innerHTML = "<a href='javascript:return true;' onclick='editrow(this); return false'>edit</a>";
}

function buildrow (row) {
    for (var i = 0; i < 5; i ++) row.insertCell(row.cells.length);
    row.cells[0].innerHTML = "<a style='font-size: normal; color: #336699' href='#' onclick='sendrow(this)'; return false'>add</a>";
    row.cells[4].innerHTML = "<a href='javascript:return true;' onclick='removerow(this); return false'>delete</a>";
    return row;
}

function addrow() {contable.add();}
function getrow(a) {return a.parentNode.parentNode;}
function saverow(a) {contable.save(getrow(a));}
function editrow(a) {contable.edit(getrow(a));}
function removerow(a) {contable.remove(getrow(a));}
function sendrow(a) {contable.send(getrow(a))};

function ConTable (id, onsave, onremove, onadd) {
    this.id = id;
    this.onsave = onsave || function () {};
    this.onremove = onremove || function () {};
    this.onadd = onadd || function () {};

    this.table = function() {return $(this.id)};
    this.add = function () {
        var table = this.table();
        var row = table.insertRow(table.rows.length);
        makeedit(buildrow(row));
    };
    

    this.cellval = function (c) {return c.firstChild && c.firstChild.value
                                 || c.firstChild && c.firstChild.nodeValue
                                 || ""}

    this.alias = function (row) {return this.cellval(row.cells[1])};
    this.val = function (row) {return this.cellval(row.cells[2])};

    this.send = function (row) {this.onadd(this.alias(row))};
    this.edit = function (row) {makeedit(row)};
    this.save = function (row) {makefinal(row); this.onsave(this.alias(row), this.val(row))};
    this.remove = function (row) {var a = this.alias(row); this.table().deleteRow(row.rowIndex); this.onremove(a)};
}



    
