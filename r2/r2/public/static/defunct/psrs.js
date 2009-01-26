var Prototype={
Version:'1.3.1',
emptyFunction:function(){}
};
var Class={
create:function(){
return function(){
this.initialize.apply(this,arguments);
}
}
};
Object.extend=function(destination,source){
for(property in source){
destination[property]=source[property];
}
return destination;
};
Object.prototype.extend=function(object){
return Object.extend.apply(this,[this,object]);
};
Function.prototype.bind=function(object){
var __method=this;
return function(){
__method.apply(object,arguments);
}
};
var Try={
these:function(){
var returnValue;
for(var i=0;i<arguments.length;i++){
var lambda=arguments[i];
try{
returnValue=lambda();
break;
}catch(e){}
}
return returnValue;
}
};
function $(){
var elements=new Array();
for(var i=0;i<arguments.length;i++){
var element=arguments[i];
if(typeof element=='string')
element=document.getElementById(element);
if(arguments.length==1) 
return element;
elements.push(element);
}
return elements;
}
if(!Array.prototype.push){
Array.prototype.push=function(){
var startLength=this.length;
for(var i=0;i<arguments.length;i++)
this[startLength+i]=arguments[i];
return this.length;
}
}
if(!Function.prototype.apply){
Function.prototype.apply=function(object,parameters){
var parameterStrings=new Array();
if(!object)object=window;
if(!parameters)parameters=new Array();
for(var i=0;i<parameters.length;i++)
parameterStrings[i]='parameters['+i+']';
object.__apply__=this;
var result=eval('object.__apply__('+ 
parameterStrings.join(', ')+')');
object.__apply__=null;
return result;
}
};
var Ajax={
getTransport:function(){
return Try.these(
function(){return new ActiveXObject('Msxml2.XMLHTTP')},
function(){return new ActiveXObject('Microsoft.XMLHTTP')},
function(){return new XMLHttpRequest()}
)||false;
}
};
Ajax.Base=function(){};
Ajax.Base.prototype={
setOptions:function(options){
this.options={
method:'post',
asynchronous:true,
parameters:''
}.extend(options||{});
},
responseIsSuccess:function(){
return this.transport.status==undefined
||this.transport.status==0 
||(this.transport.status>=200&&this.transport.status<300);
},
responseIsFailure:function(){
return!this.responseIsSuccess();
}
};
Ajax.Request=Class.create();
Ajax.Request.Events= 
['Uninitialized','Loading','Loaded','Interactive','Complete'];
Ajax.Request.prototype=(new Ajax.Base()).extend({
initialize:function(url,options){
this.transport=Ajax.getTransport();
this.setOptions(options);
this.request(url);
},
request:function(url){
var parameters=this.options.parameters||'';
if(parameters.length>0)parameters+='&_=';
try{
if(this.options.method=='get')
url+='?'+parameters;
this.transport.open(this.options.method,url,
this.options.asynchronous);
if(this.options.asynchronous){
this.transport.onreadystatechange=this.onStateChange.bind(this);
setTimeout((function(){this.respondToReadyState(1)}).bind(this),10);
}
this.setRequestHeaders();
var body=this.options.postBody?this.options.postBody:parameters;
this.transport.send(this.options.method=='post'?body:null);
}catch(e){
}
},
setRequestHeaders:function(){
var requestHeaders= 
['X-Requested-With','XMLHttpRequest',
'X-Prototype-Version',Prototype.Version];
if(this.options.method=='post'){
requestHeaders.push('Content-type', 
'application/x-www-form-urlencoded');
if(this.transport.overrideMimeType)
requestHeaders.push('Connection','close');
}
if(this.options.requestHeaders)
requestHeaders.push.apply(requestHeaders,this.options.requestHeaders);
for(var i=0;i<requestHeaders.length;i+=2)
this.transport.setRequestHeader(requestHeaders[i],requestHeaders[i+1]);
},
onStateChange:function(){
var readyState=this.transport.readyState;
if(readyState!=1)
this.respondToReadyState(this.transport.readyState);
},
respondToReadyState:function(readyState){
var event=Ajax.Request.Events[readyState];
if(event=='Complete')
(this.options['on'+this.transport.status]
||this.options['on'+(this.responseIsSuccess()?'Success':'Failure')]
||Prototype.emptyFunction)(this.transport);
(this.options['on'+event]||Prototype.emptyFunction)(this.transport);
if(event=='Complete')
this.transport.onreadystatechange=Prototype.emptyFunction;
}
});
