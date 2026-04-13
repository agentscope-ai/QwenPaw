import{g as ae,s as re,q as ne,p as ce,a as le,b as oe,_ as c,c as Q,d as ht,I as ue,K as de,L as fe,e as he,M as ke,N as me,l as U,O as ye,P as Nt,Q as Rt,R as ge,S as pe,T as ve,U as Te,V as be,W as xe,X as we,Y as Yt,Z as Bt,$ as zt,a0 as qt,a1 as Xt,a2 as _e,k as De,j as Ce,y as Ee,u as Se}from"./ui-vendor-BxhhDuQu.js";import{d as A,o as Ie,c as Ae,a as Fe,p as Le}from"./utils-vendor-BeBZsNhg.js";import"./react-vendor-Bnyb1WTF.js";import"./markdown-vendor-BOqIb_Fi.js";var xt=(function(){var t=c(function(k,l,o,d){for(o=o||{},d=k.length;d--;o[k[d]]=l);return o},"o"),s=[6,8,10,12,13,14,15,16,17,18,20,21,22,23,24,25,26,27,28,29,30,31,33,35,36,38,40],a=[1,26],n=[1,27],r=[1,28],f=[1,29],g=[1,30],E=[1,31],L=[1,32],Y=[1,33],C=[1,34],M=[1,9],B=[1,10],O=[1,11],P=[1,12],_=[1,13],$=[1,14],tt=[1,15],et=[1,16],it=[1,19],H=[1,20],st=[1,21],at=[1,22],rt=[1,23],nt=[1,25],m=[1,35],T={trace:c(function(){},"trace"),yy:{},symbols_:{error:2,start:3,gantt:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NL:10,weekday:11,weekday_monday:12,weekday_tuesday:13,weekday_wednesday:14,weekday_thursday:15,weekday_friday:16,weekday_saturday:17,weekday_sunday:18,weekend:19,weekend_friday:20,weekend_saturday:21,dateFormat:22,inclusiveEndDates:23,topAxis:24,axisFormat:25,tickInterval:26,excludes:27,includes:28,todayMarker:29,title:30,acc_title:31,acc_title_value:32,acc_descr:33,acc_descr_value:34,acc_descr_multiline_value:35,section:36,clickStatement:37,taskTxt:38,taskData:39,click:40,callbackname:41,callbackargs:42,href:43,clickStatementDebug:44,$accept:0,$end:1},terminals_:{2:"error",4:"gantt",6:"EOF",8:"SPACE",10:"NL",12:"weekday_monday",13:"weekday_tuesday",14:"weekday_wednesday",15:"weekday_thursday",16:"weekday_friday",17:"weekday_saturday",18:"weekday_sunday",20:"weekend_friday",21:"weekend_saturday",22:"dateFormat",23:"inclusiveEndDates",24:"topAxis",25:"axisFormat",26:"tickInterval",27:"excludes",28:"includes",29:"todayMarker",30:"title",31:"acc_title",32:"acc_title_value",33:"acc_descr",34:"acc_descr_value",35:"acc_descr_multiline_value",36:"section",38:"taskTxt",39:"taskData",40:"click",41:"callbackname",42:"callbackargs",43:"href"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[19,1],[19,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,1],[9,2],[37,2],[37,3],[37,3],[37,4],[37,3],[37,4],[37,2],[44,2],[44,3],[44,3],[44,4],[44,3],[44,4],[44,2]],performAction:c(function(l,o,d,u,y,i,S){var e=i.length-1;switch(y){case 1:return i[e-1];case 2:this.$=[];break;case 3:i[e-1].push(i[e]),this.$=i[e-1];break;case 4:case 5:this.$=i[e];break;case 6:case 7:this.$=[];break;case 8:u.setWeekday("monday");break;case 9:u.setWeekday("tuesday");break;case 10:u.setWeekday("wednesday");break;case 11:u.setWeekday("thursday");break;case 12:u.setWeekday("friday");break;case 13:u.setWeekday("saturday");break;case 14:u.setWeekday("sunday");break;case 15:u.setWeekend("friday");break;case 16:u.setWeekend("saturday");break;case 17:u.setDateFormat(i[e].substr(11)),this.$=i[e].substr(11);break;case 18:u.enableInclusiveEndDates(),this.$=i[e].substr(18);break;case 19:u.TopAxis(),this.$=i[e].substr(8);break;case 20:u.setAxisFormat(i[e].substr(11)),this.$=i[e].substr(11);break;case 21:u.setTickInterval(i[e].substr(13)),this.$=i[e].substr(13);break;case 22:u.setExcludes(i[e].substr(9)),this.$=i[e].substr(9);break;case 23:u.setIncludes(i[e].substr(9)),this.$=i[e].substr(9);break;case 24:u.setTodayMarker(i[e].substr(12)),this.$=i[e].substr(12);break;case 27:u.setDiagramTitle(i[e].substr(6)),this.$=i[e].substr(6);break;case 28:this.$=i[e].trim(),u.setAccTitle(this.$);break;case 29:case 30:this.$=i[e].trim(),u.setAccDescription(this.$);break;case 31:u.addSection(i[e].substr(8)),this.$=i[e].substr(8);break;case 33:u.addTask(i[e-1],i[e]),this.$="task";break;case 34:this.$=i[e-1],u.setClickEvent(i[e-1],i[e],null);break;case 35:this.$=i[e-2],u.setClickEvent(i[e-2],i[e-1],i[e]);break;case 36:this.$=i[e-2],u.setClickEvent(i[e-2],i[e-1],null),u.setLink(i[e-2],i[e]);break;case 37:this.$=i[e-3],u.setClickEvent(i[e-3],i[e-2],i[e-1]),u.setLink(i[e-3],i[e]);break;case 38:this.$=i[e-2],u.setClickEvent(i[e-2],i[e],null),u.setLink(i[e-2],i[e-1]);break;case 39:this.$=i[e-3],u.setClickEvent(i[e-3],i[e-1],i[e]),u.setLink(i[e-3],i[e-2]);break;case 40:this.$=i[e-1],u.setLink(i[e-1],i[e]);break;case 41:case 47:this.$=i[e-1]+" "+i[e];break;case 42:case 43:case 45:this.$=i[e-2]+" "+i[e-1]+" "+i[e];break;case 44:case 46:this.$=i[e-3]+" "+i[e-2]+" "+i[e-1]+" "+i[e];break}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},t(s,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:17,12:a,13:n,14:r,15:f,16:g,17:E,18:L,19:18,20:Y,21:C,22:M,23:B,24:O,25:P,26:_,27:$,28:tt,29:et,30:it,31:H,33:st,35:at,36:rt,37:24,38:nt,40:m},t(s,[2,7],{1:[2,1]}),t(s,[2,3]),{9:36,11:17,12:a,13:n,14:r,15:f,16:g,17:E,18:L,19:18,20:Y,21:C,22:M,23:B,24:O,25:P,26:_,27:$,28:tt,29:et,30:it,31:H,33:st,35:at,36:rt,37:24,38:nt,40:m},t(s,[2,5]),t(s,[2,6]),t(s,[2,17]),t(s,[2,18]),t(s,[2,19]),t(s,[2,20]),t(s,[2,21]),t(s,[2,22]),t(s,[2,23]),t(s,[2,24]),t(s,[2,25]),t(s,[2,26]),t(s,[2,27]),{32:[1,37]},{34:[1,38]},t(s,[2,30]),t(s,[2,31]),t(s,[2,32]),{39:[1,39]},t(s,[2,8]),t(s,[2,9]),t(s,[2,10]),t(s,[2,11]),t(s,[2,12]),t(s,[2,13]),t(s,[2,14]),t(s,[2,15]),t(s,[2,16]),{41:[1,40],43:[1,41]},t(s,[2,4]),t(s,[2,28]),t(s,[2,29]),t(s,[2,33]),t(s,[2,34],{42:[1,42],43:[1,43]}),t(s,[2,40],{41:[1,44]}),t(s,[2,35],{43:[1,45]}),t(s,[2,36]),t(s,[2,38],{42:[1,46]}),t(s,[2,37]),t(s,[2,39])],defaultActions:{},parseError:c(function(l,o){if(o.recoverable)this.trace(l);else{var d=new Error(l);throw d.hash=o,d}},"parseError"),parse:c(function(l){var o=this,d=[0],u=[],y=[null],i=[],S=this.table,e="",h=0,D=0,w=2,x=1,F=i.slice.call(arguments,1),v=Object.create(this.lexer),z={yy:{}};for(var ct in this.yy)Object.prototype.hasOwnProperty.call(this.yy,ct)&&(z.yy[ct]=this.yy[ct]);v.setInput(l,z.yy),z.yy.lexer=v,z.yy.parser=this,typeof v.yylloc>"u"&&(v.yylloc={});var pt=v.yylloc;i.push(pt);var ie=v.options&&v.options.ranges;typeof z.yy.parseError=="function"?this.parseError=z.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function se(W){d.length=d.length-2*W,y.length=y.length-W,i.length=i.length-W}c(se,"popStack");function Ot(){var W;return W=u.pop()||v.lex()||x,typeof W!="number"&&(W instanceof Array&&(u=W,W=u.pop()),W=o.symbols_[W]||W),W}c(Ot,"lex");for(var V,j,N,vt,K={},dt,q,Pt,ft;;){if(j=d[d.length-1],this.defaultActions[j]?N=this.defaultActions[j]:((V===null||typeof V>"u")&&(V=Ot()),N=S[j]&&S[j][V]),typeof N>"u"||!N.length||!N[0]){var Tt="";ft=[];for(dt in S[j])this.terminals_[dt]&&dt>w&&ft.push("'"+this.terminals_[dt]+"'");v.showPosition?Tt="Parse error on line "+(h+1)+`:
`+v.showPosition()+`
Expecting `+ft.join(", ")+", got '"+(this.terminals_[V]||V)+"'":Tt="Parse error on line "+(h+1)+": Unexpected "+(V==x?"end of input":"'"+(this.terminals_[V]||V)+"'"),this.parseError(Tt,{text:v.match,token:this.terminals_[V]||V,line:v.yylineno,loc:pt,expected:ft})}if(N[0]instanceof Array&&N.length>1)throw new Error("Parse Error: multiple actions possible at state: "+j+", token: "+V);switch(N[0]){case 1:d.push(V),y.push(v.yytext),i.push(v.yylloc),d.push(N[1]),V=null,D=v.yyleng,e=v.yytext,h=v.yylineno,pt=v.yylloc;break;case 2:if(q=this.productions_[N[1]][1],K.$=y[y.length-q],K._$={first_line:i[i.length-(q||1)].first_line,last_line:i[i.length-1].last_line,first_column:i[i.length-(q||1)].first_column,last_column:i[i.length-1].last_column},ie&&(K._$.range=[i[i.length-(q||1)].range[0],i[i.length-1].range[1]]),vt=this.performAction.apply(K,[e,D,h,z.yy,N[1],y,i].concat(F)),typeof vt<"u")return vt;q&&(d=d.slice(0,-1*q*2),y=y.slice(0,-1*q),i=i.slice(0,-1*q)),d.push(this.productions_[N[1]][0]),y.push(K.$),i.push(K._$),Pt=S[d[d.length-2]][d[d.length-1]],d.push(Pt);break;case 3:return!0}}return!0},"parse")},b=(function(){var k={EOF:1,parseError:c(function(o,d){if(this.yy.parser)this.yy.parser.parseError(o,d);else throw new Error(o)},"parseError"),setInput:c(function(l,o){return this.yy=o||this.yy||{},this._input=l,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:c(function(){var l=this._input[0];this.yytext+=l,this.yyleng++,this.offset++,this.match+=l,this.matched+=l;var o=l.match(/(?:\r\n?|\n).*/g);return o?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),l},"input"),unput:c(function(l){var o=l.length,d=l.split(/(?:\r\n?|\n)/g);this._input=l+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-o),this.offset-=o;var u=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),d.length-1&&(this.yylineno-=d.length-1);var y=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:d?(d.length===u.length?this.yylloc.first_column:0)+u[u.length-d.length].length-d[0].length:this.yylloc.first_column-o},this.options.ranges&&(this.yylloc.range=[y[0],y[0]+this.yyleng-o]),this.yyleng=this.yytext.length,this},"unput"),more:c(function(){return this._more=!0,this},"more"),reject:c(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:c(function(l){this.unput(this.match.slice(l))},"less"),pastInput:c(function(){var l=this.matched.substr(0,this.matched.length-this.match.length);return(l.length>20?"...":"")+l.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:c(function(){var l=this.match;return l.length<20&&(l+=this._input.substr(0,20-l.length)),(l.substr(0,20)+(l.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:c(function(){var l=this.pastInput(),o=new Array(l.length+1).join("-");return l+this.upcomingInput()+`
`+o+"^"},"showPosition"),test_match:c(function(l,o){var d,u,y;if(this.options.backtrack_lexer&&(y={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(y.yylloc.range=this.yylloc.range.slice(0))),u=l[0].match(/(?:\r\n?|\n).*/g),u&&(this.yylineno+=u.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:u?u[u.length-1].length-u[u.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+l[0].length},this.yytext+=l[0],this.match+=l[0],this.matches=l,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(l[0].length),this.matched+=l[0],d=this.performAction.call(this,this.yy,this,o,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),d)return d;if(this._backtrack){for(var i in y)this[i]=y[i];return!1}return!1},"test_match"),next:c(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var l,o,d,u;this._more||(this.yytext="",this.match="");for(var y=this._currentRules(),i=0;i<y.length;i++)if(d=this._input.match(this.rules[y[i]]),d&&(!o||d[0].length>o[0].length)){if(o=d,u=i,this.options.backtrack_lexer){if(l=this.test_match(d,y[i]),l!==!1)return l;if(this._backtrack){o=!1;continue}else return!1}else if(!this.options.flex)break}return o?(l=this.test_match(o,y[u]),l!==!1?l:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:c(function(){var o=this.next();return o||this.lex()},"lex"),begin:c(function(o){this.conditionStack.push(o)},"begin"),popState:c(function(){var o=this.conditionStack.length-1;return o>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:c(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:c(function(o){return o=this.conditionStack.length-1-Math.abs(o||0),o>=0?this.conditionStack[o]:"INITIAL"},"topState"),pushState:c(function(o){this.begin(o)},"pushState"),stateStackSize:c(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:c(function(o,d,u,y){switch(u){case 0:return this.begin("open_directive"),"open_directive";case 1:return this.begin("acc_title"),31;case 2:return this.popState(),"acc_title_value";case 3:return this.begin("acc_descr"),33;case 4:return this.popState(),"acc_descr_value";case 5:this.begin("acc_descr_multiline");break;case 6:this.popState();break;case 7:return"acc_descr_multiline_value";case 8:break;case 9:break;case 10:break;case 11:return 10;case 12:break;case 13:break;case 14:this.begin("href");break;case 15:this.popState();break;case 16:return 43;case 17:this.begin("callbackname");break;case 18:this.popState();break;case 19:this.popState(),this.begin("callbackargs");break;case 20:return 41;case 21:this.popState();break;case 22:return 42;case 23:this.begin("click");break;case 24:this.popState();break;case 25:return 40;case 26:return 4;case 27:return 22;case 28:return 23;case 29:return 24;case 30:return 25;case 31:return 26;case 32:return 28;case 33:return 27;case 34:return 29;case 35:return 12;case 36:return 13;case 37:return 14;case 38:return 15;case 39:return 16;case 40:return 17;case 41:return 18;case 42:return 20;case 43:return 21;case 44:return"date";case 45:return 30;case 46:return"accDescription";case 47:return 36;case 48:return 38;case 49:return 39;case 50:return":";case 51:return 6;case 52:return"INVALID"}},"anonymous"),rules:[/^(?:%%\{)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:%%(?!\{)*[^\n]*)/i,/^(?:[^\}]%%*[^\n]*)/i,/^(?:%%*[^\n]*[\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:%[^\n]*)/i,/^(?:href[\s]+["])/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:call[\s]+)/i,/^(?:\([\s]*\))/i,/^(?:\()/i,/^(?:[^(]*)/i,/^(?:\))/i,/^(?:[^)]*)/i,/^(?:click[\s]+)/i,/^(?:[\s\n])/i,/^(?:[^\s\n]*)/i,/^(?:gantt\b)/i,/^(?:dateFormat\s[^#\n;]+)/i,/^(?:inclusiveEndDates\b)/i,/^(?:topAxis\b)/i,/^(?:axisFormat\s[^#\n;]+)/i,/^(?:tickInterval\s[^#\n;]+)/i,/^(?:includes\s[^#\n;]+)/i,/^(?:excludes\s[^#\n;]+)/i,/^(?:todayMarker\s[^\n;]+)/i,/^(?:weekday\s+monday\b)/i,/^(?:weekday\s+tuesday\b)/i,/^(?:weekday\s+wednesday\b)/i,/^(?:weekday\s+thursday\b)/i,/^(?:weekday\s+friday\b)/i,/^(?:weekday\s+saturday\b)/i,/^(?:weekday\s+sunday\b)/i,/^(?:weekend\s+friday\b)/i,/^(?:weekend\s+saturday\b)/i,/^(?:\d\d\d\d-\d\d-\d\d\b)/i,/^(?:title\s[^\n]+)/i,/^(?:accDescription\s[^#\n;]+)/i,/^(?:section\s[^\n]+)/i,/^(?:[^:\n]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[6,7],inclusive:!1},acc_descr:{rules:[4],inclusive:!1},acc_title:{rules:[2],inclusive:!1},callbackargs:{rules:[21,22],inclusive:!1},callbackname:{rules:[18,19,20],inclusive:!1},href:{rules:[15,16],inclusive:!1},click:{rules:[24,25],inclusive:!1},INITIAL:{rules:[0,1,3,5,8,9,10,11,12,13,14,17,23,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52],inclusive:!0}}};return k})();T.lexer=b;function p(){this.yy={}}return c(p,"Parser"),p.prototype=T,T.Parser=p,new p})();xt.parser=xt;var Me=xt;A.extend(Ie);A.extend(Ae);A.extend(Fe);var jt={friday:5,saturday:6},R="",Ct="",Et=void 0,St="",lt=[],ot=[],It=new Map,At=[],yt=[],J="",Ft="",Ht=["active","done","crit","milestone","vert"],Lt=[],ut=!1,Mt=!1,Vt="sunday",gt="saturday",wt=0,Ve=c(function(){At=[],yt=[],J="",Lt=[],kt=0,Dt=void 0,mt=void 0,I=[],R="",Ct="",Ft="",Et=void 0,St="",lt=[],ot=[],ut=!1,Mt=!1,wt=0,It=new Map,Ee(),Vt="sunday",gt="saturday"},"clear"),We=c(function(t){Ct=t},"setAxisFormat"),Oe=c(function(){return Ct},"getAxisFormat"),Pe=c(function(t){Et=t},"setTickInterval"),Ne=c(function(){return Et},"getTickInterval"),Re=c(function(t){St=t},"setTodayMarker"),Ye=c(function(){return St},"getTodayMarker"),Be=c(function(t){R=t},"setDateFormat"),ze=c(function(){ut=!0},"enableInclusiveEndDates"),qe=c(function(){return ut},"endDatesAreInclusive"),Xe=c(function(){Mt=!0},"enableTopAxis"),je=c(function(){return Mt},"topAxisEnabled"),Ue=c(function(t){Ft=t},"setDisplayMode"),Ge=c(function(){return Ft},"getDisplayMode"),He=c(function(){return R},"getDateFormat"),Ke=c(function(t){lt=t.toLowerCase().split(/[\s,]+/)},"setIncludes"),Qe=c(function(){return lt},"getIncludes"),Ze=c(function(t){ot=t.toLowerCase().split(/[\s,]+/)},"setExcludes"),Je=c(function(){return ot},"getExcludes"),$e=c(function(){return It},"getLinks"),ti=c(function(t){J=t,At.push(t)},"addSection"),ei=c(function(){return At},"getSections"),ii=c(function(){let t=Ut();const s=10;let a=0;for(;!t&&a<s;)t=Ut(),a++;return yt=I,yt},"getTasks"),Kt=c(function(t,s,a,n){const r=t.format(s.trim()),f=t.format("YYYY-MM-DD");return n.includes(r)||n.includes(f)?!1:a.includes("weekends")&&(t.isoWeekday()===jt[gt]||t.isoWeekday()===jt[gt]+1)||a.includes(t.format("dddd").toLowerCase())?!0:a.includes(r)||a.includes(f)},"isInvalidDate"),si=c(function(t){Vt=t},"setWeekday"),ai=c(function(){return Vt},"getWeekday"),ri=c(function(t){gt=t},"setWeekend"),Qt=c(function(t,s,a,n){if(!a.length||t.manualEndTime)return;let r;t.startTime instanceof Date?r=A(t.startTime):r=A(t.startTime,s,!0),r=r.add(1,"d");let f;t.endTime instanceof Date?f=A(t.endTime):f=A(t.endTime,s,!0);const[g,E]=ni(r,f,s,a,n);t.endTime=g.toDate(),t.renderEndTime=E},"checkTaskDates"),ni=c(function(t,s,a,n,r){let f=!1,g=null;for(;t<=s;)f||(g=s.toDate()),f=Kt(t,a,n,r),f&&(s=s.add(1,"d")),t=t.add(1,"d");return[s,g]},"fixTaskDates"),_t=c(function(t,s,a){if(a=a.trim(),c(E=>{const L=E.trim();return L==="x"||L==="X"},"isTimestampFormat")(s)&&/^\d+$/.test(a))return new Date(Number(a));const f=/^after\s+(?<ids>[\d\w- ]+)/.exec(a);if(f!==null){let E=null;for(const Y of f.groups.ids.split(" ")){let C=G(Y);C!==void 0&&(!E||C.endTime>E.endTime)&&(E=C)}if(E)return E.endTime;const L=new Date;return L.setHours(0,0,0,0),L}let g=A(a,s.trim(),!0);if(g.isValid())return g.toDate();{U.debug("Invalid date:"+a),U.debug("With date format:"+s.trim());const E=new Date(a);if(E===void 0||isNaN(E.getTime())||E.getFullYear()<-1e4||E.getFullYear()>1e4)throw new Error("Invalid date:"+a);return E}},"getStartDate"),Zt=c(function(t){const s=/^(\d+(?:\.\d+)?)([Mdhmswy]|ms)$/.exec(t.trim());return s!==null?[Number.parseFloat(s[1]),s[2]]:[NaN,"ms"]},"parseDuration"),Jt=c(function(t,s,a,n=!1){a=a.trim();const f=/^until\s+(?<ids>[\d\w- ]+)/.exec(a);if(f!==null){let C=null;for(const B of f.groups.ids.split(" ")){let O=G(B);O!==void 0&&(!C||O.startTime<C.startTime)&&(C=O)}if(C)return C.startTime;const M=new Date;return M.setHours(0,0,0,0),M}let g=A(a,s.trim(),!0);if(g.isValid())return n&&(g=g.add(1,"d")),g.toDate();let E=A(t);const[L,Y]=Zt(a);if(!Number.isNaN(L)){const C=E.add(L,Y);C.isValid()&&(E=C)}return E.toDate()},"getEndDate"),kt=0,Z=c(function(t){return t===void 0?(kt=kt+1,"task"+kt):t},"parseId"),ci=c(function(t,s){let a;s.substr(0,1)===":"?a=s.substr(1,s.length):a=s;const n=a.split(","),r={};Wt(n,r,Ht);for(let g=0;g<n.length;g++)n[g]=n[g].trim();let f="";switch(n.length){case 1:r.id=Z(),r.startTime=t.endTime,f=n[0];break;case 2:r.id=Z(),r.startTime=_t(void 0,R,n[0]),f=n[1];break;case 3:r.id=Z(n[0]),r.startTime=_t(void 0,R,n[1]),f=n[2];break}return f&&(r.endTime=Jt(r.startTime,R,f,ut),r.manualEndTime=A(f,"YYYY-MM-DD",!0).isValid(),Qt(r,R,ot,lt)),r},"compileData"),li=c(function(t,s){let a;s.substr(0,1)===":"?a=s.substr(1,s.length):a=s;const n=a.split(","),r={};Wt(n,r,Ht);for(let f=0;f<n.length;f++)n[f]=n[f].trim();switch(n.length){case 1:r.id=Z(),r.startTime={type:"prevTaskEnd",id:t},r.endTime={data:n[0]};break;case 2:r.id=Z(),r.startTime={type:"getStartDate",startData:n[0]},r.endTime={data:n[1]};break;case 3:r.id=Z(n[0]),r.startTime={type:"getStartDate",startData:n[1]},r.endTime={data:n[2]};break}return r},"parseData"),Dt,mt,I=[],$t={},oi=c(function(t,s){const a={section:J,type:J,processed:!1,manualEndTime:!1,renderEndTime:null,raw:{data:s},task:t,classes:[]},n=li(mt,s);a.raw.startTime=n.startTime,a.raw.endTime=n.endTime,a.id=n.id,a.prevTaskId=mt,a.active=n.active,a.done=n.done,a.crit=n.crit,a.milestone=n.milestone,a.vert=n.vert,a.order=wt,wt++;const r=I.push(a);mt=a.id,$t[a.id]=r-1},"addTask"),G=c(function(t){const s=$t[t];return I[s]},"findTaskById"),ui=c(function(t,s){const a={section:J,type:J,description:t,task:t,classes:[]},n=ci(Dt,s);a.startTime=n.startTime,a.endTime=n.endTime,a.id=n.id,a.active=n.active,a.done=n.done,a.crit=n.crit,a.milestone=n.milestone,a.vert=n.vert,Dt=a,yt.push(a)},"addTaskOrg"),Ut=c(function(){const t=c(function(a){const n=I[a];let r="";switch(I[a].raw.startTime.type){case"prevTaskEnd":{const f=G(n.prevTaskId);n.startTime=f.endTime;break}case"getStartDate":r=_t(void 0,R,I[a].raw.startTime.startData),r&&(I[a].startTime=r);break}return I[a].startTime&&(I[a].endTime=Jt(I[a].startTime,R,I[a].raw.endTime.data,ut),I[a].endTime&&(I[a].processed=!0,I[a].manualEndTime=A(I[a].raw.endTime.data,"YYYY-MM-DD",!0).isValid(),Qt(I[a],R,ot,lt))),I[a].processed},"compileTask");let s=!0;for(const[a,n]of I.entries())t(a),s=s&&n.processed;return s},"compileTasks"),di=c(function(t,s){let a=s;Q().securityLevel!=="loose"&&(a=Ce.sanitizeUrl(s)),t.split(",").forEach(function(n){G(n)!==void 0&&(ee(n,()=>{window.open(a,"_self")}),It.set(n,a))}),te(t,"clickable")},"setLink"),te=c(function(t,s){t.split(",").forEach(function(a){let n=G(a);n!==void 0&&n.classes.push(s)})},"setClass"),fi=c(function(t,s,a){if(Q().securityLevel!=="loose"||s===void 0)return;let n=[];if(typeof a=="string"){n=a.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);for(let f=0;f<n.length;f++){let g=n[f].trim();g.startsWith('"')&&g.endsWith('"')&&(g=g.substr(1,g.length-2)),n[f]=g}}n.length===0&&n.push(t),G(t)!==void 0&&ee(t,()=>{Se.runFunc(s,...n)})},"setClickFun"),ee=c(function(t,s){Lt.push(function(){const a=document.querySelector(`[id="${t}"]`);a!==null&&a.addEventListener("click",function(){s()})},function(){const a=document.querySelector(`[id="${t}-text"]`);a!==null&&a.addEventListener("click",function(){s()})})},"pushFun"),hi=c(function(t,s,a){t.split(",").forEach(function(n){fi(n,s,a)}),te(t,"clickable")},"setClickEvent"),ki=c(function(t){Lt.forEach(function(s){s(t)})},"bindFunctions"),mi={getConfig:c(()=>Q().gantt,"getConfig"),clear:Ve,setDateFormat:Be,getDateFormat:He,enableInclusiveEndDates:ze,endDatesAreInclusive:qe,enableTopAxis:Xe,topAxisEnabled:je,setAxisFormat:We,getAxisFormat:Oe,setTickInterval:Pe,getTickInterval:Ne,setTodayMarker:Re,getTodayMarker:Ye,setAccTitle:oe,getAccTitle:le,setDiagramTitle:ce,getDiagramTitle:ne,setDisplayMode:Ue,getDisplayMode:Ge,setAccDescription:re,getAccDescription:ae,addSection:ti,getSections:ei,getTasks:ii,addTask:oi,findTaskById:G,addTaskOrg:ui,setIncludes:Ke,getIncludes:Qe,setExcludes:Ze,getExcludes:Je,setClickEvent:hi,setLink:di,getLinks:$e,bindFunctions:ki,parseDuration:Zt,isInvalidDate:Kt,setWeekday:si,getWeekday:ai,setWeekend:ri};function Wt(t,s,a){let n=!0;for(;n;)n=!1,a.forEach(function(r){const f="^\\s*"+r+"\\s*$",g=new RegExp(f);t[0].match(g)&&(s[r]=!0,t.shift(1),n=!0)})}c(Wt,"getTaskTags");A.extend(Le);var yi=c(function(){U.debug("Something is calling, setConf, remove the call")},"setConf"),Gt={monday:we,tuesday:xe,wednesday:be,thursday:Te,friday:ve,saturday:pe,sunday:ge},gi=c((t,s)=>{let a=[...t].map(()=>-1/0),n=[...t].sort((f,g)=>f.startTime-g.startTime||f.order-g.order),r=0;for(const f of n)for(let g=0;g<a.length;g++)if(f.startTime>=a[g]){a[g]=f.endTime,f.order=g+s,g>r&&(r=g);break}return r},"getMaxIntersections"),X,bt=1e4,pi=c(function(t,s,a,n){const r=Q().gantt,f=Q().securityLevel;let g;f==="sandbox"&&(g=ht("#i"+s));const E=f==="sandbox"?ht(g.nodes()[0].contentDocument.body):ht("body"),L=f==="sandbox"?g.nodes()[0].contentDocument:document,Y=L.getElementById(s);X=Y.parentElement.offsetWidth,X===void 0&&(X=1200),r.useWidth!==void 0&&(X=r.useWidth);const C=n.db.getTasks();let M=[];for(const m of C)M.push(m.type);M=nt(M);const B={};let O=2*r.topPadding;if(n.db.getDisplayMode()==="compact"||r.displayMode==="compact"){const m={};for(const b of C)m[b.section]===void 0?m[b.section]=[b]:m[b.section].push(b);let T=0;for(const b of Object.keys(m)){const p=gi(m[b],T)+1;T+=p,O+=p*(r.barHeight+r.barGap),B[b]=p}}else{O+=C.length*(r.barHeight+r.barGap);for(const m of M)B[m]=C.filter(T=>T.type===m).length}Y.setAttribute("viewBox","0 0 "+X+" "+O);const P=E.select(`[id="${s}"]`),_=ue().domain([de(C,function(m){return m.startTime}),fe(C,function(m){return m.endTime})]).rangeRound([0,X-r.leftPadding-r.rightPadding]);function $(m,T){const b=m.startTime,p=T.startTime;let k=0;return b>p?k=1:b<p&&(k=-1),k}c($,"taskCompare"),C.sort($),tt(C,X,O),he(P,O,X,r.useMaxWidth),P.append("text").text(n.db.getDiagramTitle()).attr("x",X/2).attr("y",r.titleTopMargin).attr("class","titleText");function tt(m,T,b){const p=r.barHeight,k=p+r.barGap,l=r.topPadding,o=r.leftPadding,d=ke().domain([0,M.length]).range(["#00B9FA","#F95002"]).interpolate(me);it(k,l,o,T,b,m,n.db.getExcludes(),n.db.getIncludes()),st(o,l,T,b),et(m,k,l,o,p,d,T),at(k,l),rt(o,l,T,b)}c(tt,"makeGantt");function et(m,T,b,p,k,l,o){m.sort((e,h)=>e.vert===h.vert?0:e.vert?1:-1);const u=[...new Set(m.map(e=>e.order))].map(e=>m.find(h=>h.order===e));P.append("g").selectAll("rect").data(u).enter().append("rect").attr("x",0).attr("y",function(e,h){return h=e.order,h*T+b-2}).attr("width",function(){return o-r.rightPadding/2}).attr("height",T).attr("class",function(e){for(const[h,D]of M.entries())if(e.type===D)return"section section"+h%r.numberSectionStyles;return"section section0"}).enter();const y=P.append("g").selectAll("rect").data(m).enter(),i=n.db.getLinks();if(y.append("rect").attr("id",function(e){return e.id}).attr("rx",3).attr("ry",3).attr("x",function(e){return e.milestone?_(e.startTime)+p+.5*(_(e.endTime)-_(e.startTime))-.5*k:_(e.startTime)+p}).attr("y",function(e,h){return h=e.order,e.vert?r.gridLineStartPadding:h*T+b}).attr("width",function(e){return e.milestone?k:e.vert?.08*k:_(e.renderEndTime||e.endTime)-_(e.startTime)}).attr("height",function(e){return e.vert?C.length*(r.barHeight+r.barGap)+r.barHeight*2:k}).attr("transform-origin",function(e,h){return h=e.order,(_(e.startTime)+p+.5*(_(e.endTime)-_(e.startTime))).toString()+"px "+(h*T+b+.5*k).toString()+"px"}).attr("class",function(e){const h="task";let D="";e.classes.length>0&&(D=e.classes.join(" "));let w=0;for(const[F,v]of M.entries())e.type===v&&(w=F%r.numberSectionStyles);let x="";return e.active?e.crit?x+=" activeCrit":x=" active":e.done?e.crit?x=" doneCrit":x=" done":e.crit&&(x+=" crit"),x.length===0&&(x=" task"),e.milestone&&(x=" milestone "+x),e.vert&&(x=" vert "+x),x+=w,x+=" "+D,h+x}),y.append("text").attr("id",function(e){return e.id+"-text"}).text(function(e){return e.task}).attr("font-size",r.fontSize).attr("x",function(e){let h=_(e.startTime),D=_(e.renderEndTime||e.endTime);if(e.milestone&&(h+=.5*(_(e.endTime)-_(e.startTime))-.5*k,D=h+k),e.vert)return _(e.startTime)+p;const w=this.getBBox().width;return w>D-h?D+w+1.5*r.leftPadding>o?h+p-5:D+p+5:(D-h)/2+h+p}).attr("y",function(e,h){return e.vert?r.gridLineStartPadding+C.length*(r.barHeight+r.barGap)+60:(h=e.order,h*T+r.barHeight/2+(r.fontSize/2-2)+b)}).attr("text-height",k).attr("class",function(e){const h=_(e.startTime);let D=_(e.endTime);e.milestone&&(D=h+k);const w=this.getBBox().width;let x="";e.classes.length>0&&(x=e.classes.join(" "));let F=0;for(const[z,ct]of M.entries())e.type===ct&&(F=z%r.numberSectionStyles);let v="";return e.active&&(e.crit?v="activeCritText"+F:v="activeText"+F),e.done?e.crit?v=v+" doneCritText"+F:v=v+" doneText"+F:e.crit&&(v=v+" critText"+F),e.milestone&&(v+=" milestoneText"),e.vert&&(v+=" vertText"),w>D-h?D+w+1.5*r.leftPadding>o?x+" taskTextOutsideLeft taskTextOutside"+F+" "+v:x+" taskTextOutsideRight taskTextOutside"+F+" "+v+" width-"+w:x+" taskText taskText"+F+" "+v+" width-"+w}),Q().securityLevel==="sandbox"){let e;e=ht("#i"+s);const h=e.nodes()[0].contentDocument;y.filter(function(D){return i.has(D.id)}).each(function(D){var w=h.querySelector("#"+D.id),x=h.querySelector("#"+D.id+"-text");const F=w.parentNode;var v=h.createElement("a");v.setAttribute("xlink:href",i.get(D.id)),v.setAttribute("target","_top"),F.appendChild(v),v.appendChild(w),v.appendChild(x)})}}c(et,"drawRects");function it(m,T,b,p,k,l,o,d){if(o.length===0&&d.length===0)return;let u,y;for(const{startTime:w,endTime:x}of l)(u===void 0||w<u)&&(u=w),(y===void 0||x>y)&&(y=x);if(!u||!y)return;if(A(y).diff(A(u),"year")>5){U.warn("The difference between the min and max time is more than 5 years. This will cause performance issues. Skipping drawing exclude days.");return}const i=n.db.getDateFormat(),S=[];let e=null,h=A(u);for(;h.valueOf()<=y;)n.db.isInvalidDate(h,i,o,d)?e?e.end=h:e={start:h,end:h}:e&&(S.push(e),e=null),h=h.add(1,"d");P.append("g").selectAll("rect").data(S).enter().append("rect").attr("id",w=>"exclude-"+w.start.format("YYYY-MM-DD")).attr("x",w=>_(w.start.startOf("day"))+b).attr("y",r.gridLineStartPadding).attr("width",w=>_(w.end.endOf("day"))-_(w.start.startOf("day"))).attr("height",k-T-r.gridLineStartPadding).attr("transform-origin",function(w,x){return(_(w.start)+b+.5*(_(w.end)-_(w.start))).toString()+"px "+(x*m+.5*k).toString()+"px"}).attr("class","exclude-range")}c(it,"drawExcludeDays");function H(m,T,b,p){if(b<=0||m>T)return 1/0;const k=T-m,l=A.duration({[p??"day"]:b}).asMilliseconds();return l<=0?1/0:Math.ceil(k/l)}c(H,"getEstimatedTickCount");function st(m,T,b,p){const k=n.db.getDateFormat(),l=n.db.getAxisFormat();let o;l?o=l:k==="D"?o="%d":o=r.axisFormat??"%Y-%m-%d";let d=ye(_).tickSize(-p+T+r.gridLineStartPadding).tickFormat(Nt(o));const y=/^([1-9]\d*)(millisecond|second|minute|hour|day|week|month)$/.exec(n.db.getTickInterval()||r.tickInterval);if(y!==null){const i=parseInt(y[1],10);if(isNaN(i)||i<=0)U.warn(`Invalid tick interval value: "${y[1]}". Skipping custom tick interval.`);else{const S=y[2],e=n.db.getWeekday()||r.weekday,h=_.domain(),D=h[0],w=h[1],x=H(D,w,i,S);if(x>bt)U.warn(`The tick interval "${i}${S}" would generate ${x} ticks, which exceeds the maximum allowed (${bt}). This may indicate an invalid date or time range. Skipping custom tick interval.`);else switch(S){case"millisecond":d.ticks(Xt.every(i));break;case"second":d.ticks(qt.every(i));break;case"minute":d.ticks(zt.every(i));break;case"hour":d.ticks(Bt.every(i));break;case"day":d.ticks(Yt.every(i));break;case"week":d.ticks(Gt[e].every(i));break;case"month":d.ticks(Rt.every(i));break}}}if(P.append("g").attr("class","grid").attr("transform","translate("+m+", "+(p-50)+")").call(d).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10).attr("dy","1em"),n.db.topAxisEnabled()||r.topAxis){let i=_e(_).tickSize(-p+T+r.gridLineStartPadding).tickFormat(Nt(o));if(y!==null){const S=parseInt(y[1],10);if(isNaN(S)||S<=0)U.warn(`Invalid tick interval value: "${y[1]}". Skipping custom tick interval.`);else{const e=y[2],h=n.db.getWeekday()||r.weekday,D=_.domain(),w=D[0],x=D[1];if(H(w,x,S,e)<=bt)switch(e){case"millisecond":i.ticks(Xt.every(S));break;case"second":i.ticks(qt.every(S));break;case"minute":i.ticks(zt.every(S));break;case"hour":i.ticks(Bt.every(S));break;case"day":i.ticks(Yt.every(S));break;case"week":i.ticks(Gt[h].every(S));break;case"month":i.ticks(Rt.every(S));break}}}P.append("g").attr("class","grid").attr("transform","translate("+m+", "+T+")").call(i).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10)}}c(st,"makeGrid");function at(m,T){let b=0;const p=Object.keys(B).map(k=>[k,B[k]]);P.append("g").selectAll("text").data(p).enter().append(function(k){const l=k[0].split(De.lineBreakRegex),o=-(l.length-1)/2,d=L.createElementNS("http://www.w3.org/2000/svg","text");d.setAttribute("dy",o+"em");for(const[u,y]of l.entries()){const i=L.createElementNS("http://www.w3.org/2000/svg","tspan");i.setAttribute("alignment-baseline","central"),i.setAttribute("x","10"),u>0&&i.setAttribute("dy","1em"),i.textContent=y,d.appendChild(i)}return d}).attr("x",10).attr("y",function(k,l){if(l>0)for(let o=0;o<l;o++)return b+=p[l-1][1],k[1]*m/2+b*m+T;else return k[1]*m/2+T}).attr("font-size",r.sectionFontSize).attr("class",function(k){for(const[l,o]of M.entries())if(k[0]===o)return"sectionTitle sectionTitle"+l%r.numberSectionStyles;return"sectionTitle"})}c(at,"vertLabels");function rt(m,T,b,p){const k=n.db.getTodayMarker();if(k==="off")return;const l=P.append("g").attr("class","today"),o=new Date,d=l.append("line");d.attr("x1",_(o)+m).attr("x2",_(o)+m).attr("y1",r.titleTopMargin).attr("y2",p-r.titleTopMargin).attr("class","today"),k!==""&&d.attr("style",k.replace(/,/g,";"))}c(rt,"drawToday");function nt(m){const T={},b=[];for(let p=0,k=m.length;p<k;++p)Object.prototype.hasOwnProperty.call(T,m[p])||(T[m[p]]=!0,b.push(m[p]));return b}c(nt,"checkUnique")},"draw"),vi={setConf:yi,draw:pi},Ti=c(t=>`
  .mermaid-main-font {
        font-family: ${t.fontFamily};
  }

  .exclude-range {
    fill: ${t.excludeBkgColor};
  }

  .section {
    stroke: none;
    opacity: 0.2;
  }

  .section0 {
    fill: ${t.sectionBkgColor};
  }

  .section2 {
    fill: ${t.sectionBkgColor2};
  }

  .section1,
  .section3 {
    fill: ${t.altSectionBkgColor};
    opacity: 0.2;
  }

  .sectionTitle0 {
    fill: ${t.titleColor};
  }

  .sectionTitle1 {
    fill: ${t.titleColor};
  }

  .sectionTitle2 {
    fill: ${t.titleColor};
  }

  .sectionTitle3 {
    fill: ${t.titleColor};
  }

  .sectionTitle {
    text-anchor: start;
    font-family: ${t.fontFamily};
  }


  /* Grid and axis */

  .grid .tick {
    stroke: ${t.gridColor};
    opacity: 0.8;
    shape-rendering: crispEdges;
  }

  .grid .tick text {
    font-family: ${t.fontFamily};
    fill: ${t.textColor};
  }

  .grid path {
    stroke-width: 0;
  }


  /* Today line */

  .today {
    fill: none;
    stroke: ${t.todayLineColor};
    stroke-width: 2px;
  }


  /* Task styling */

  /* Default task */

  .task {
    stroke-width: 2;
  }

  .taskText {
    text-anchor: middle;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideRight {
    fill: ${t.taskTextDarkColor};
    text-anchor: start;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideLeft {
    fill: ${t.taskTextDarkColor};
    text-anchor: end;
  }


  /* Special case clickable */

  .task.clickable {
    cursor: pointer;
  }

  .taskText.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideLeft.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideRight.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }


  /* Specific task settings for the sections*/

  .taskText0,
  .taskText1,
  .taskText2,
  .taskText3 {
    fill: ${t.taskTextColor};
  }

  .task0,
  .task1,
  .task2,
  .task3 {
    fill: ${t.taskBkgColor};
    stroke: ${t.taskBorderColor};
  }

  .taskTextOutside0,
  .taskTextOutside2
  {
    fill: ${t.taskTextOutsideColor};
  }

  .taskTextOutside1,
  .taskTextOutside3 {
    fill: ${t.taskTextOutsideColor};
  }


  /* Active task */

  .active0,
  .active1,
  .active2,
  .active3 {
    fill: ${t.activeTaskBkgColor};
    stroke: ${t.activeTaskBorderColor};
  }

  .activeText0,
  .activeText1,
  .activeText2,
  .activeText3 {
    fill: ${t.taskTextDarkColor} !important;
  }


  /* Completed task */

  .done0,
  .done1,
  .done2,
  .done3 {
    stroke: ${t.doneTaskBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
  }

  .doneText0,
  .doneText1,
  .doneText2,
  .doneText3 {
    fill: ${t.taskTextDarkColor} !important;
  }


  /* Tasks on the critical line */

  .crit0,
  .crit1,
  .crit2,
  .crit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.critBkgColor};
    stroke-width: 2;
  }

  .activeCrit0,
  .activeCrit1,
  .activeCrit2,
  .activeCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.activeTaskBkgColor};
    stroke-width: 2;
  }

  .doneCrit0,
  .doneCrit1,
  .doneCrit2,
  .doneCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
    cursor: pointer;
    shape-rendering: crispEdges;
  }

  .milestone {
    transform: rotate(45deg) scale(0.8,0.8);
  }

  .milestoneText {
    font-style: italic;
  }
  .doneCritText0,
  .doneCritText1,
  .doneCritText2,
  .doneCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  .vert {
    stroke: ${t.vertLineColor};
  }

  .vertText {
    font-size: 15px;
    text-anchor: middle;
    fill: ${t.vertLineColor} !important;
  }

  .activeCritText0,
  .activeCritText1,
  .activeCritText2,
  .activeCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  .titleText {
    text-anchor: middle;
    font-size: 18px;
    fill: ${t.titleColor||t.textColor};
    font-family: ${t.fontFamily};
  }
`,"getStyles"),bi=Ti,Ci={parser:Me,db:mi,renderer:vi,styles:bi};export{Ci as diagram};
