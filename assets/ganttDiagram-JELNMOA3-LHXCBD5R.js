import{g as he,s as me,q as ke,p as ye,a as ve,b as ge,_ as c,c as lt,d as gt,aD as pe,aE as Te,aF as xe,e as be,P as we,aG as _e,aH as j,l as nt,aI as De,aJ as qt,aK as Gt,aL as Se,aM as Ce,aN as Me,aO as Ee,aP as Ie,aQ as $e,aR as Ye,aS as jt,aT as Xt,aU as Ut,aV as Zt,aW as Qt,aX as Fe,k as Ae,j as Le,y as We,u as Oe}from"./mermaid-DN4X81Jr.js";import{g as Ct}from"./router-QjqbnSNQ.js";import"./markdown-Cetf2IPD.js";var pt={exports:{}},Pe=pt.exports,Kt;function Ve(){return Kt||(Kt=1,(function(t,a){(function(i,r){t.exports=r()})(Pe,(function(){var i="day";return function(r,n,k){var y=function(A){return A.add(4-A.isoWeekday(),i)},_=n.prototype;_.isoWeekYear=function(){return y(this).year()},_.isoWeek=function(A){if(!this.$utils().u(A))return this.add(7*(A-this.isoWeek()),i);var b,L,V,N,z=y(this),M=(b=this.isoWeekYear(),L=this.$u,V=(L?k.utc:k)().year(b).startOf("year"),N=4-V.isoWeekday(),V.isoWeekday()>4&&(N+=7),V.add(N,i));return z.diff(M,"week")+1},_.isoWeekday=function(A){return this.$utils().u(A)?this.day()||7:this.day(this.day()%7?A:A-7)};var W=_.startOf;_.startOf=function(A,b){var L=this.$utils(),V=!!L.u(b)||b;return L.p(A)==="isoweek"?V?this.date(this.date()-(this.isoWeekday()-1)).startOf("day"):this.date(this.date()-1-(this.isoWeekday()-1)+7).endOf("day"):W.bind(this)(A,b)}}}))})(pt)),pt.exports}var Ne=Ve();const ze=Ct(Ne);var Tt={exports:{}},Re=Tt.exports,Jt;function He(){return Jt||(Jt=1,(function(t,a){(function(i,r){t.exports=r()})(Re,(function(){var i={LTS:"h:mm:ss A",LT:"h:mm A",L:"MM/DD/YYYY",LL:"MMMM D, YYYY",LLL:"MMMM D, YYYY h:mm A",LLLL:"dddd, MMMM D, YYYY h:mm A"},r=/(\[[^[]*\])|([-_:/.,()\s]+)|(A|a|Q|YYYY|YY?|ww?|MM?M?M?|Do|DD?|hh?|HH?|mm?|ss?|S{1,3}|z|ZZ?)/g,n=/\d/,k=/\d\d/,y=/\d\d?/,_=/\d*[^-_:/,()\s\d]+/,W={},A=function(D){return(D=+D)+(D>68?1900:2e3)},b=function(D){return function(S){this[D]=+S}},L=[/[+-]\d\d:?(\d\d)?|Z/,function(D){(this.zone||(this.zone={})).offset=(function(S){if(!S||S==="Z")return 0;var O=S.match(/([+-]|\d\d)/g),Y=60*O[1]+(+O[2]||0);return Y===0?0:O[0]==="+"?-Y:Y})(D)}],V=function(D){var S=W[D];return S&&(S.indexOf?S:S.s.concat(S.f))},N=function(D,S){var O,Y=W.meridiem;if(Y){for(var R=1;R<=24;R+=1)if(D.indexOf(Y(R,0,S))>-1){O=R>12;break}}else O=D===(S?"pm":"PM");return O},z={A:[_,function(D){this.afternoon=N(D,!1)}],a:[_,function(D){this.afternoon=N(D,!0)}],Q:[n,function(D){this.month=3*(D-1)+1}],S:[n,function(D){this.milliseconds=100*+D}],SS:[k,function(D){this.milliseconds=10*+D}],SSS:[/\d{3}/,function(D){this.milliseconds=+D}],s:[y,b("seconds")],ss:[y,b("seconds")],m:[y,b("minutes")],mm:[y,b("minutes")],H:[y,b("hours")],h:[y,b("hours")],HH:[y,b("hours")],hh:[y,b("hours")],D:[y,b("day")],DD:[k,b("day")],Do:[_,function(D){var S=W.ordinal,O=D.match(/\d+/);if(this.day=O[0],S)for(var Y=1;Y<=31;Y+=1)S(Y).replace(/\[|\]/g,"")===D&&(this.day=Y)}],w:[y,b("week")],ww:[k,b("week")],M:[y,b("month")],MM:[k,b("month")],MMM:[_,function(D){var S=V("months"),O=(V("monthsShort")||S.map((function(Y){return Y.slice(0,3)}))).indexOf(D)+1;if(O<1)throw new Error;this.month=O%12||O}],MMMM:[_,function(D){var S=V("months").indexOf(D)+1;if(S<1)throw new Error;this.month=S%12||S}],Y:[/[+-]?\d+/,b("year")],YY:[k,function(D){this.year=A(D)}],YYYY:[/\d{4}/,b("year")],Z:L,ZZ:L};function M(D){var S,O;S=D,O=W&&W.formats;for(var Y=(D=S.replace(/(\[[^\]]+])|(LTS?|l{1,4}|L{1,4})/g,(function(p,g,v){var f=v&&v.toUpperCase();return g||O[v]||i[v]||O[f].replace(/(\[[^\]]+])|(MMMM|MM|DD|dddd)/g,(function(o,l,h){return l||h.slice(1)}))}))).match(r),R=Y.length,q=0;q<R;q+=1){var E=Y[q],T=z[E],d=T&&T[0],u=T&&T[1];Y[q]=u?{regex:d,parser:u}:E.replace(/^\[|\]$/g,"")}return function(p){for(var g={},v=0,f=0;v<R;v+=1){var o=Y[v];if(typeof o=="string")f+=o.length;else{var l=o.regex,h=o.parser,m=p.slice(f),x=l.exec(m)[0];h.call(g,x),p=p.replace(x,"")}}return(function(s){var P=s.afternoon;if(P!==void 0){var e=s.hours;P?e<12&&(s.hours+=12):e===12&&(s.hours=0),delete s.afternoon}})(g),g}}return function(D,S,O){O.p.customParseFormat=!0,D&&D.parseTwoDigitYear&&(A=D.parseTwoDigitYear);var Y=S.prototype,R=Y.parse;Y.parse=function(q){var E=q.date,T=q.utc,d=q.args;this.$u=T;var u=d[1];if(typeof u=="string"){var p=d[2]===!0,g=d[3]===!0,v=p||g,f=d[2];g&&(f=d[2]),W=this.$locale(),!p&&f&&(W=O.Ls[f]),this.$d=(function(m,x,s,P){try{if(["x","X"].indexOf(x)>-1)return new Date((x==="X"?1e3:1)*m);var e=M(x)(m),w=e.year,F=e.month,$=e.day,I=e.hours,G=e.minutes,C=e.seconds,Q=e.milliseconds,st=e.zone,ot=e.week,ft=new Date,ht=$||(w||F?1:ft.getDate()),ct=w||ft.getFullYear(),H=0;w&&!F||(H=F>0?F-1:ft.getMonth());var Z,X=I||0,it=G||0,K=C||0,rt=Q||0;return st?new Date(Date.UTC(ct,H,ht,X,it,K,rt+60*st.offset*1e3)):s?new Date(Date.UTC(ct,H,ht,X,it,K,rt)):(Z=new Date(ct,H,ht,X,it,K,rt),ot&&(Z=P(Z).week(ot).toDate()),Z)}catch{return new Date("")}})(E,u,T,O),this.init(),f&&f!==!0&&(this.$L=this.locale(f).$L),v&&E!=this.format(u)&&(this.$d=new Date("")),W={}}else if(u instanceof Array)for(var o=u.length,l=1;l<=o;l+=1){d[1]=u[l-1];var h=O.apply(this,d);if(h.isValid()){this.$d=h.$d,this.$L=h.$L,this.init();break}l===o&&(this.$d=new Date(""))}else R.call(this,q)}}}))})(Tt)),Tt.exports}var Be=He();const qe=Ct(Be);var xt={exports:{}},Ge=xt.exports,te;function je(){return te||(te=1,(function(t,a){(function(i,r){t.exports=r()})(Ge,(function(){return function(i,r){var n=r.prototype,k=n.format;n.format=function(y){var _=this,W=this.$locale();if(!this.isValid())return k.bind(this)(y);var A=this.$utils(),b=(y||"YYYY-MM-DDTHH:mm:ssZ").replace(/\[([^\]]+)]|Q|wo|ww|w|WW|W|zzz|z|gggg|GGGG|Do|X|x|k{1,2}|S/g,(function(L){switch(L){case"Q":return Math.ceil((_.$M+1)/3);case"Do":return W.ordinal(_.$D);case"gggg":return _.weekYear();case"GGGG":return _.isoWeekYear();case"wo":return W.ordinal(_.week(),"W");case"w":case"ww":return A.s(_.week(),L==="w"?1:2,"0");case"W":case"WW":return A.s(_.isoWeek(),L==="W"?1:2,"0");case"k":case"kk":return A.s(String(_.$H===0?24:_.$H),L==="k"?1:2,"0");case"X":return Math.floor(_.$d.getTime()/1e3);case"x":return _.$d.getTime();case"z":return"["+_.offsetName()+"]";case"zzz":return"["+_.offsetName("long")+"]";default:return L}}));return k.bind(this)(b)}}}))})(xt)),xt.exports}var Xe=je();const Ue=Ct(Xe);var bt={exports:{}},Ze=bt.exports,ee;function Qe(){return ee||(ee=1,(function(t,a){(function(i,r){t.exports=r()})(Ze,(function(){var i,r,n=1e3,k=6e4,y=36e5,_=864e5,W=/\[([^\]]+)]|Y{1,4}|M{1,4}|D{1,2}|d{1,4}|H{1,2}|h{1,2}|a|A|m{1,2}|s{1,2}|Z{1,2}|SSS/g,A=31536e6,b=2628e6,L=/^(-|\+)?P(?:([-+]?[0-9,.]*)Y)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)W)?(?:([-+]?[0-9,.]*)D)?(?:T(?:([-+]?[0-9,.]*)H)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)S)?)?$/,V={years:A,months:b,days:_,hours:y,minutes:k,seconds:n,milliseconds:1,weeks:6048e5},N=function(E){return E instanceof R},z=function(E,T,d){return new R(E,d,T.$l)},M=function(E){return r.p(E)+"s"},D=function(E){return E<0},S=function(E){return D(E)?Math.ceil(E):Math.floor(E)},O=function(E){return Math.abs(E)},Y=function(E,T){return E?D(E)?{negative:!0,format:""+O(E)+T}:{negative:!1,format:""+E+T}:{negative:!1,format:""}},R=(function(){function E(d,u,p){var g=this;if(this.$d={},this.$l=p,d===void 0&&(this.$ms=0,this.parseFromMilliseconds()),u)return z(d*V[M(u)],this);if(typeof d=="number")return this.$ms=d,this.parseFromMilliseconds(),this;if(typeof d=="object")return Object.keys(d).forEach((function(o){g.$d[M(o)]=d[o]})),this.calMilliseconds(),this;if(typeof d=="string"){var v=d.match(L);if(v){var f=v.slice(2).map((function(o){return o!=null?Number(o):0}));return this.$d.years=f[0],this.$d.months=f[1],this.$d.weeks=f[2],this.$d.days=f[3],this.$d.hours=f[4],this.$d.minutes=f[5],this.$d.seconds=f[6],this.calMilliseconds(),this}}return this}var T=E.prototype;return T.calMilliseconds=function(){var d=this;this.$ms=Object.keys(this.$d).reduce((function(u,p){return u+(d.$d[p]||0)*V[p]}),0)},T.parseFromMilliseconds=function(){var d=this.$ms;this.$d.years=S(d/A),d%=A,this.$d.months=S(d/b),d%=b,this.$d.days=S(d/_),d%=_,this.$d.hours=S(d/y),d%=y,this.$d.minutes=S(d/k),d%=k,this.$d.seconds=S(d/n),d%=n,this.$d.milliseconds=d},T.toISOString=function(){var d=Y(this.$d.years,"Y"),u=Y(this.$d.months,"M"),p=+this.$d.days||0;this.$d.weeks&&(p+=7*this.$d.weeks);var g=Y(p,"D"),v=Y(this.$d.hours,"H"),f=Y(this.$d.minutes,"M"),o=this.$d.seconds||0;this.$d.milliseconds&&(o+=this.$d.milliseconds/1e3,o=Math.round(1e3*o)/1e3);var l=Y(o,"S"),h=d.negative||u.negative||g.negative||v.negative||f.negative||l.negative,m=v.format||f.format||l.format?"T":"",x=(h?"-":"")+"P"+d.format+u.format+g.format+m+v.format+f.format+l.format;return x==="P"||x==="-P"?"P0D":x},T.toJSON=function(){return this.toISOString()},T.format=function(d){var u=d||"YYYY-MM-DDTHH:mm:ss",p={Y:this.$d.years,YY:r.s(this.$d.years,2,"0"),YYYY:r.s(this.$d.years,4,"0"),M:this.$d.months,MM:r.s(this.$d.months,2,"0"),D:this.$d.days,DD:r.s(this.$d.days,2,"0"),H:this.$d.hours,HH:r.s(this.$d.hours,2,"0"),m:this.$d.minutes,mm:r.s(this.$d.minutes,2,"0"),s:this.$d.seconds,ss:r.s(this.$d.seconds,2,"0"),SSS:r.s(this.$d.milliseconds,3,"0")};return u.replace(W,(function(g,v){return v||String(p[g])}))},T.as=function(d){return this.$ms/V[M(d)]},T.get=function(d){var u=this.$ms,p=M(d);return p==="milliseconds"?u%=1e3:u=p==="weeks"?S(u/V[p]):this.$d[p],u||0},T.add=function(d,u,p){var g;return g=u?d*V[M(u)]:N(d)?d.$ms:z(d,this).$ms,z(this.$ms+g*(p?-1:1),this)},T.subtract=function(d,u){return this.add(d,u,!0)},T.locale=function(d){var u=this.clone();return u.$l=d,u},T.clone=function(){return z(this.$ms,this)},T.humanize=function(d){return i().add(this.$ms,"ms").locale(this.$l).fromNow(!d)},T.valueOf=function(){return this.asMilliseconds()},T.milliseconds=function(){return this.get("milliseconds")},T.asMilliseconds=function(){return this.as("milliseconds")},T.seconds=function(){return this.get("seconds")},T.asSeconds=function(){return this.as("seconds")},T.minutes=function(){return this.get("minutes")},T.asMinutes=function(){return this.as("minutes")},T.hours=function(){return this.get("hours")},T.asHours=function(){return this.as("hours")},T.days=function(){return this.get("days")},T.asDays=function(){return this.as("days")},T.weeks=function(){return this.get("weeks")},T.asWeeks=function(){return this.as("weeks")},T.months=function(){return this.get("months")},T.asMonths=function(){return this.as("months")},T.years=function(){return this.get("years")},T.asYears=function(){return this.as("years")},E})(),q=function(E,T,d){return E.add(T.years()*d,"y").add(T.months()*d,"M").add(T.days()*d,"d").add(T.hours()*d,"h").add(T.minutes()*d,"m").add(T.seconds()*d,"s").add(T.milliseconds()*d,"ms")};return function(E,T,d){i=d,r=d().$utils(),d.duration=function(g,v){var f=d.locale();return z(g,{$l:f},v)},d.isDuration=N;var u=T.prototype.add,p=T.prototype.subtract;T.prototype.add=function(g,v){return N(g)?q(this,g,1):u.bind(this)(g,v)},T.prototype.subtract=function(g,v){return N(g)?q(this,g,-1):p.bind(this)(g,v)}}}))})(bt)),bt.exports}var Ke=Qe();const Je=Ct(Ke);var It=(function(){var t=c(function(f,o,l,h){for(l=l||{},h=f.length;h--;l[f[h]]=o);return l},"o"),a=[6,8,10,12,13,14,15,16,17,18,20,21,22,23,24,25,26,27,28,29,30,31,33,35,36,38,40],i=[1,26],r=[1,27],n=[1,28],k=[1,29],y=[1,30],_=[1,31],W=[1,32],A=[1,33],b=[1,34],L=[1,9],V=[1,10],N=[1,11],z=[1,12],M=[1,13],D=[1,14],S=[1,15],O=[1,16],Y=[1,19],R=[1,20],q=[1,21],E=[1,22],T=[1,23],d=[1,25],u=[1,35],p={trace:c(function(){},"trace"),yy:{},symbols_:{error:2,start:3,gantt:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NL:10,weekday:11,weekday_monday:12,weekday_tuesday:13,weekday_wednesday:14,weekday_thursday:15,weekday_friday:16,weekday_saturday:17,weekday_sunday:18,weekend:19,weekend_friday:20,weekend_saturday:21,dateFormat:22,inclusiveEndDates:23,topAxis:24,axisFormat:25,tickInterval:26,excludes:27,includes:28,todayMarker:29,title:30,acc_title:31,acc_title_value:32,acc_descr:33,acc_descr_value:34,acc_descr_multiline_value:35,section:36,clickStatement:37,taskTxt:38,taskData:39,click:40,callbackname:41,callbackargs:42,href:43,clickStatementDebug:44,$accept:0,$end:1},terminals_:{2:"error",4:"gantt",6:"EOF",8:"SPACE",10:"NL",12:"weekday_monday",13:"weekday_tuesday",14:"weekday_wednesday",15:"weekday_thursday",16:"weekday_friday",17:"weekday_saturday",18:"weekday_sunday",20:"weekend_friday",21:"weekend_saturday",22:"dateFormat",23:"inclusiveEndDates",24:"topAxis",25:"axisFormat",26:"tickInterval",27:"excludes",28:"includes",29:"todayMarker",30:"title",31:"acc_title",32:"acc_title_value",33:"acc_descr",34:"acc_descr_value",35:"acc_descr_multiline_value",36:"section",38:"taskTxt",39:"taskData",40:"click",41:"callbackname",42:"callbackargs",43:"href"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[19,1],[19,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,1],[9,2],[37,2],[37,3],[37,3],[37,4],[37,3],[37,4],[37,2],[44,2],[44,3],[44,3],[44,4],[44,3],[44,4],[44,2]],performAction:c(function(o,l,h,m,x,s,P){var e=s.length-1;switch(x){case 1:return s[e-1];case 2:this.$=[];break;case 3:s[e-1].push(s[e]),this.$=s[e-1];break;case 4:case 5:this.$=s[e];break;case 6:case 7:this.$=[];break;case 8:m.setWeekday("monday");break;case 9:m.setWeekday("tuesday");break;case 10:m.setWeekday("wednesday");break;case 11:m.setWeekday("thursday");break;case 12:m.setWeekday("friday");break;case 13:m.setWeekday("saturday");break;case 14:m.setWeekday("sunday");break;case 15:m.setWeekend("friday");break;case 16:m.setWeekend("saturday");break;case 17:m.setDateFormat(s[e].substr(11)),this.$=s[e].substr(11);break;case 18:m.enableInclusiveEndDates(),this.$=s[e].substr(18);break;case 19:m.TopAxis(),this.$=s[e].substr(8);break;case 20:m.setAxisFormat(s[e].substr(11)),this.$=s[e].substr(11);break;case 21:m.setTickInterval(s[e].substr(13)),this.$=s[e].substr(13);break;case 22:m.setExcludes(s[e].substr(9)),this.$=s[e].substr(9);break;case 23:m.setIncludes(s[e].substr(9)),this.$=s[e].substr(9);break;case 24:m.setTodayMarker(s[e].substr(12)),this.$=s[e].substr(12);break;case 27:m.setDiagramTitle(s[e].substr(6)),this.$=s[e].substr(6);break;case 28:this.$=s[e].trim(),m.setAccTitle(this.$);break;case 29:case 30:this.$=s[e].trim(),m.setAccDescription(this.$);break;case 31:m.addSection(s[e].substr(8)),this.$=s[e].substr(8);break;case 33:m.addTask(s[e-1],s[e]),this.$="task";break;case 34:this.$=s[e-1],m.setClickEvent(s[e-1],s[e],null);break;case 35:this.$=s[e-2],m.setClickEvent(s[e-2],s[e-1],s[e]);break;case 36:this.$=s[e-2],m.setClickEvent(s[e-2],s[e-1],null),m.setLink(s[e-2],s[e]);break;case 37:this.$=s[e-3],m.setClickEvent(s[e-3],s[e-2],s[e-1]),m.setLink(s[e-3],s[e]);break;case 38:this.$=s[e-2],m.setClickEvent(s[e-2],s[e],null),m.setLink(s[e-2],s[e-1]);break;case 39:this.$=s[e-3],m.setClickEvent(s[e-3],s[e-1],s[e]),m.setLink(s[e-3],s[e-2]);break;case 40:this.$=s[e-1],m.setLink(s[e-1],s[e]);break;case 41:case 47:this.$=s[e-1]+" "+s[e];break;case 42:case 43:case 45:this.$=s[e-2]+" "+s[e-1]+" "+s[e];break;case 44:case 46:this.$=s[e-3]+" "+s[e-2]+" "+s[e-1]+" "+s[e];break}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},t(a,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:17,12:i,13:r,14:n,15:k,16:y,17:_,18:W,19:18,20:A,21:b,22:L,23:V,24:N,25:z,26:M,27:D,28:S,29:O,30:Y,31:R,33:q,35:E,36:T,37:24,38:d,40:u},t(a,[2,7],{1:[2,1]}),t(a,[2,3]),{9:36,11:17,12:i,13:r,14:n,15:k,16:y,17:_,18:W,19:18,20:A,21:b,22:L,23:V,24:N,25:z,26:M,27:D,28:S,29:O,30:Y,31:R,33:q,35:E,36:T,37:24,38:d,40:u},t(a,[2,5]),t(a,[2,6]),t(a,[2,17]),t(a,[2,18]),t(a,[2,19]),t(a,[2,20]),t(a,[2,21]),t(a,[2,22]),t(a,[2,23]),t(a,[2,24]),t(a,[2,25]),t(a,[2,26]),t(a,[2,27]),{32:[1,37]},{34:[1,38]},t(a,[2,30]),t(a,[2,31]),t(a,[2,32]),{39:[1,39]},t(a,[2,8]),t(a,[2,9]),t(a,[2,10]),t(a,[2,11]),t(a,[2,12]),t(a,[2,13]),t(a,[2,14]),t(a,[2,15]),t(a,[2,16]),{41:[1,40],43:[1,41]},t(a,[2,4]),t(a,[2,28]),t(a,[2,29]),t(a,[2,33]),t(a,[2,34],{42:[1,42],43:[1,43]}),t(a,[2,40],{41:[1,44]}),t(a,[2,35],{43:[1,45]}),t(a,[2,36]),t(a,[2,38],{42:[1,46]}),t(a,[2,37]),t(a,[2,39])],defaultActions:{},parseError:c(function(o,l){if(l.recoverable)this.trace(o);else{var h=new Error(o);throw h.hash=l,h}},"parseError"),parse:c(function(o){var l=this,h=[0],m=[],x=[null],s=[],P=this.table,e="",w=0,F=0,$=2,I=1,G=s.slice.call(arguments,1),C=Object.create(this.lexer),Q={yy:{}};for(var st in this.yy)Object.prototype.hasOwnProperty.call(this.yy,st)&&(Q.yy[st]=this.yy[st]);C.setInput(o,Q.yy),Q.yy.lexer=C,Q.yy.parser=this,typeof C.yylloc>"u"&&(C.yylloc={});var ot=C.yylloc;s.push(ot);var ft=C.options&&C.options.ranges;typeof Q.yy.parseError=="function"?this.parseError=Q.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function ht(U){h.length=h.length-2*U,x.length=x.length-U,s.length=s.length-U}c(ht,"popStack");function ct(){var U;return U=m.pop()||C.lex()||I,typeof U!="number"&&(U instanceof Array&&(m=U,U=m.pop()),U=l.symbols_[U]||U),U}c(ct,"lex");for(var H,Z,X,it,K={},rt,J,Bt,vt;;){if(Z=h[h.length-1],this.defaultActions[Z]?X=this.defaultActions[Z]:((H===null||typeof H>"u")&&(H=ct()),X=P[Z]&&P[Z][H]),typeof X>"u"||!X.length||!X[0]){var Mt="";vt=[];for(rt in P[Z])this.terminals_[rt]&&rt>$&&vt.push("'"+this.terminals_[rt]+"'");C.showPosition?Mt="Parse error on line "+(w+1)+`:
`+C.showPosition()+`
Expecting `+vt.join(", ")+", got '"+(this.terminals_[H]||H)+"'":Mt="Parse error on line "+(w+1)+": Unexpected "+(H==I?"end of input":"'"+(this.terminals_[H]||H)+"'"),this.parseError(Mt,{text:C.match,token:this.terminals_[H]||H,line:C.yylineno,loc:ot,expected:vt})}if(X[0]instanceof Array&&X.length>1)throw new Error("Parse Error: multiple actions possible at state: "+Z+", token: "+H);switch(X[0]){case 1:h.push(H),x.push(C.yytext),s.push(C.yylloc),h.push(X[1]),H=null,F=C.yyleng,e=C.yytext,w=C.yylineno,ot=C.yylloc;break;case 2:if(J=this.productions_[X[1]][1],K.$=x[x.length-J],K._$={first_line:s[s.length-(J||1)].first_line,last_line:s[s.length-1].last_line,first_column:s[s.length-(J||1)].first_column,last_column:s[s.length-1].last_column},ft&&(K._$.range=[s[s.length-(J||1)].range[0],s[s.length-1].range[1]]),it=this.performAction.apply(K,[e,F,w,Q.yy,X[1],x,s].concat(G)),typeof it<"u")return it;J&&(h=h.slice(0,-1*J*2),x=x.slice(0,-1*J),s=s.slice(0,-1*J)),h.push(this.productions_[X[1]][0]),x.push(K.$),s.push(K._$),Bt=P[h[h.length-2]][h[h.length-1]],h.push(Bt);break;case 3:return!0}}return!0},"parse")},g=(function(){var f={EOF:1,parseError:c(function(l,h){if(this.yy.parser)this.yy.parser.parseError(l,h);else throw new Error(l)},"parseError"),setInput:c(function(o,l){return this.yy=l||this.yy||{},this._input=o,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:c(function(){var o=this._input[0];this.yytext+=o,this.yyleng++,this.offset++,this.match+=o,this.matched+=o;var l=o.match(/(?:\r\n?|\n).*/g);return l?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),o},"input"),unput:c(function(o){var l=o.length,h=o.split(/(?:\r\n?|\n)/g);this._input=o+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-l),this.offset-=l;var m=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),h.length-1&&(this.yylineno-=h.length-1);var x=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:h?(h.length===m.length?this.yylloc.first_column:0)+m[m.length-h.length].length-h[0].length:this.yylloc.first_column-l},this.options.ranges&&(this.yylloc.range=[x[0],x[0]+this.yyleng-l]),this.yyleng=this.yytext.length,this},"unput"),more:c(function(){return this._more=!0,this},"more"),reject:c(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:c(function(o){this.unput(this.match.slice(o))},"less"),pastInput:c(function(){var o=this.matched.substr(0,this.matched.length-this.match.length);return(o.length>20?"...":"")+o.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:c(function(){var o=this.match;return o.length<20&&(o+=this._input.substr(0,20-o.length)),(o.substr(0,20)+(o.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:c(function(){var o=this.pastInput(),l=new Array(o.length+1).join("-");return o+this.upcomingInput()+`
`+l+"^"},"showPosition"),test_match:c(function(o,l){var h,m,x;if(this.options.backtrack_lexer&&(x={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(x.yylloc.range=this.yylloc.range.slice(0))),m=o[0].match(/(?:\r\n?|\n).*/g),m&&(this.yylineno+=m.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:m?m[m.length-1].length-m[m.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+o[0].length},this.yytext+=o[0],this.match+=o[0],this.matches=o,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(o[0].length),this.matched+=o[0],h=this.performAction.call(this,this.yy,this,l,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),h)return h;if(this._backtrack){for(var s in x)this[s]=x[s];return!1}return!1},"test_match"),next:c(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var o,l,h,m;this._more||(this.yytext="",this.match="");for(var x=this._currentRules(),s=0;s<x.length;s++)if(h=this._input.match(this.rules[x[s]]),h&&(!l||h[0].length>l[0].length)){if(l=h,m=s,this.options.backtrack_lexer){if(o=this.test_match(h,x[s]),o!==!1)return o;if(this._backtrack){l=!1;continue}else return!1}else if(!this.options.flex)break}return l?(o=this.test_match(l,x[m]),o!==!1?o:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:c(function(){var l=this.next();return l||this.lex()},"lex"),begin:c(function(l){this.conditionStack.push(l)},"begin"),popState:c(function(){var l=this.conditionStack.length-1;return l>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:c(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:c(function(l){return l=this.conditionStack.length-1-Math.abs(l||0),l>=0?this.conditionStack[l]:"INITIAL"},"topState"),pushState:c(function(l){this.begin(l)},"pushState"),stateStackSize:c(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:c(function(l,h,m,x){switch(m){case 0:return this.begin("open_directive"),"open_directive";case 1:return this.begin("acc_title"),31;case 2:return this.popState(),"acc_title_value";case 3:return this.begin("acc_descr"),33;case 4:return this.popState(),"acc_descr_value";case 5:this.begin("acc_descr_multiline");break;case 6:this.popState();break;case 7:return"acc_descr_multiline_value";case 8:break;case 9:break;case 10:break;case 11:return 10;case 12:break;case 13:break;case 14:this.begin("href");break;case 15:this.popState();break;case 16:return 43;case 17:this.begin("callbackname");break;case 18:this.popState();break;case 19:this.popState(),this.begin("callbackargs");break;case 20:return 41;case 21:this.popState();break;case 22:return 42;case 23:this.begin("click");break;case 24:this.popState();break;case 25:return 40;case 26:return 4;case 27:return 22;case 28:return 23;case 29:return 24;case 30:return 25;case 31:return 26;case 32:return 28;case 33:return 27;case 34:return 29;case 35:return 12;case 36:return 13;case 37:return 14;case 38:return 15;case 39:return 16;case 40:return 17;case 41:return 18;case 42:return 20;case 43:return 21;case 44:return"date";case 45:return 30;case 46:return"accDescription";case 47:return 36;case 48:return 38;case 49:return 39;case 50:return":";case 51:return 6;case 52:return"INVALID"}},"anonymous"),rules:[/^(?:%%\{)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:%%(?!\{)*[^\n]*)/i,/^(?:[^\}]%%*[^\n]*)/i,/^(?:%%*[^\n]*[\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:%[^\n]*)/i,/^(?:href[\s]+["])/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:call[\s]+)/i,/^(?:\([\s]*\))/i,/^(?:\()/i,/^(?:[^(]*)/i,/^(?:\))/i,/^(?:[^)]*)/i,/^(?:click[\s]+)/i,/^(?:[\s\n])/i,/^(?:[^\s\n]*)/i,/^(?:gantt\b)/i,/^(?:dateFormat\s[^#\n;]+)/i,/^(?:inclusiveEndDates\b)/i,/^(?:topAxis\b)/i,/^(?:axisFormat\s[^#\n;]+)/i,/^(?:tickInterval\s[^#\n;]+)/i,/^(?:includes\s[^#\n;]+)/i,/^(?:excludes\s[^#\n;]+)/i,/^(?:todayMarker\s[^\n;]+)/i,/^(?:weekday\s+monday\b)/i,/^(?:weekday\s+tuesday\b)/i,/^(?:weekday\s+wednesday\b)/i,/^(?:weekday\s+thursday\b)/i,/^(?:weekday\s+friday\b)/i,/^(?:weekday\s+saturday\b)/i,/^(?:weekday\s+sunday\b)/i,/^(?:weekend\s+friday\b)/i,/^(?:weekend\s+saturday\b)/i,/^(?:\d\d\d\d-\d\d-\d\d\b)/i,/^(?:title\s[^\n]+)/i,/^(?:accDescription\s[^#\n;]+)/i,/^(?:section\s[^\n]+)/i,/^(?:[^:\n]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[6,7],inclusive:!1},acc_descr:{rules:[4],inclusive:!1},acc_title:{rules:[2],inclusive:!1},callbackargs:{rules:[21,22],inclusive:!1},callbackname:{rules:[18,19,20],inclusive:!1},href:{rules:[15,16],inclusive:!1},click:{rules:[24,25],inclusive:!1},INITIAL:{rules:[0,1,3,5,8,9,10,11,12,13,14,17,23,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52],inclusive:!0}}};return f})();p.lexer=g;function v(){this.yy={}}return c(v,"Parser"),v.prototype=p,p.Parser=v,new v})();It.parser=It;var ts=It;j.extend(ze);j.extend(qe);j.extend(Ue);var se={friday:5,saturday:6},tt="",At="",Lt=void 0,Wt="",mt=[],kt=[],Ot=new Map,Pt=[],Dt=[],dt="",Vt="",ne=["active","done","crit","milestone","vert"],Nt=[],yt=!1,zt=!1,Rt="sunday",St="saturday",$t=0,es=c(function(){Pt=[],Dt=[],dt="",Nt=[],wt=0,Ft=void 0,_t=void 0,B=[],tt="",At="",Vt="",Lt=void 0,Wt="",mt=[],kt=[],yt=!1,zt=!1,$t=0,Ot=new Map,We(),Rt="sunday",St="saturday"},"clear"),ss=c(function(t){At=t},"setAxisFormat"),rs=c(function(){return At},"getAxisFormat"),is=c(function(t){Lt=t},"setTickInterval"),ns=c(function(){return Lt},"getTickInterval"),as=c(function(t){Wt=t},"setTodayMarker"),os=c(function(){return Wt},"getTodayMarker"),cs=c(function(t){tt=t},"setDateFormat"),ls=c(function(){yt=!0},"enableInclusiveEndDates"),us=c(function(){return yt},"endDatesAreInclusive"),ds=c(function(){zt=!0},"enableTopAxis"),fs=c(function(){return zt},"topAxisEnabled"),hs=c(function(t){Vt=t},"setDisplayMode"),ms=c(function(){return Vt},"getDisplayMode"),ks=c(function(){return tt},"getDateFormat"),ys=c(function(t){mt=t.toLowerCase().split(/[\s,]+/)},"setIncludes"),vs=c(function(){return mt},"getIncludes"),gs=c(function(t){kt=t.toLowerCase().split(/[\s,]+/)},"setExcludes"),ps=c(function(){return kt},"getExcludes"),Ts=c(function(){return Ot},"getLinks"),xs=c(function(t){dt=t,Pt.push(t)},"addSection"),bs=c(function(){return Pt},"getSections"),ws=c(function(){let t=re();const a=10;let i=0;for(;!t&&i<a;)t=re(),i++;return Dt=B,Dt},"getTasks"),ae=c(function(t,a,i,r){const n=t.format(a.trim()),k=t.format("YYYY-MM-DD");return r.includes(n)||r.includes(k)?!1:i.includes("weekends")&&(t.isoWeekday()===se[St]||t.isoWeekday()===se[St]+1)||i.includes(t.format("dddd").toLowerCase())?!0:i.includes(n)||i.includes(k)},"isInvalidDate"),_s=c(function(t){Rt=t},"setWeekday"),Ds=c(function(){return Rt},"getWeekday"),Ss=c(function(t){St=t},"setWeekend"),oe=c(function(t,a,i,r){if(!i.length||t.manualEndTime)return;let n;t.startTime instanceof Date?n=j(t.startTime):n=j(t.startTime,a,!0),n=n.add(1,"d");let k;t.endTime instanceof Date?k=j(t.endTime):k=j(t.endTime,a,!0);const[y,_]=Cs(n,k,a,i,r);t.endTime=y.toDate(),t.renderEndTime=_},"checkTaskDates"),Cs=c(function(t,a,i,r,n){let k=!1,y=null;for(;t<=a;)k||(y=a.toDate()),k=ae(t,i,r,n),k&&(a=a.add(1,"d")),t=t.add(1,"d");return[a,y]},"fixTaskDates"),Yt=c(function(t,a,i){if(i=i.trim(),c(_=>{const W=_.trim();return W==="x"||W==="X"},"isTimestampFormat")(a)&&/^\d+$/.test(i))return new Date(Number(i));const k=/^after\s+(?<ids>[\d\w- ]+)/.exec(i);if(k!==null){let _=null;for(const A of k.groups.ids.split(" ")){let b=at(A);b!==void 0&&(!_||b.endTime>_.endTime)&&(_=b)}if(_)return _.endTime;const W=new Date;return W.setHours(0,0,0,0),W}let y=j(i,a.trim(),!0);if(y.isValid())return y.toDate();{nt.debug("Invalid date:"+i),nt.debug("With date format:"+a.trim());const _=new Date(i);if(_===void 0||isNaN(_.getTime())||_.getFullYear()<-1e4||_.getFullYear()>1e4)throw new Error("Invalid date:"+i);return _}},"getStartDate"),ce=c(function(t){const a=/^(\d+(?:\.\d+)?)([Mdhmswy]|ms)$/.exec(t.trim());return a!==null?[Number.parseFloat(a[1]),a[2]]:[NaN,"ms"]},"parseDuration"),le=c(function(t,a,i,r=!1){i=i.trim();const k=/^until\s+(?<ids>[\d\w- ]+)/.exec(i);if(k!==null){let b=null;for(const V of k.groups.ids.split(" ")){let N=at(V);N!==void 0&&(!b||N.startTime<b.startTime)&&(b=N)}if(b)return b.startTime;const L=new Date;return L.setHours(0,0,0,0),L}let y=j(i,a.trim(),!0);if(y.isValid())return r&&(y=y.add(1,"d")),y.toDate();let _=j(t);const[W,A]=ce(i);if(!Number.isNaN(W)){const b=_.add(W,A);b.isValid()&&(_=b)}return _.toDate()},"getEndDate"),wt=0,ut=c(function(t){return t===void 0?(wt=wt+1,"task"+wt):t},"parseId"),Ms=c(function(t,a){let i;a.substr(0,1)===":"?i=a.substr(1,a.length):i=a;const r=i.split(","),n={};Ht(r,n,ne);for(let y=0;y<r.length;y++)r[y]=r[y].trim();let k="";switch(r.length){case 1:n.id=ut(),n.startTime=t.endTime,k=r[0];break;case 2:n.id=ut(),n.startTime=Yt(void 0,tt,r[0]),k=r[1];break;case 3:n.id=ut(r[0]),n.startTime=Yt(void 0,tt,r[1]),k=r[2];break}return k&&(n.endTime=le(n.startTime,tt,k,yt),n.manualEndTime=j(k,"YYYY-MM-DD",!0).isValid(),oe(n,tt,kt,mt)),n},"compileData"),Es=c(function(t,a){let i;a.substr(0,1)===":"?i=a.substr(1,a.length):i=a;const r=i.split(","),n={};Ht(r,n,ne);for(let k=0;k<r.length;k++)r[k]=r[k].trim();switch(r.length){case 1:n.id=ut(),n.startTime={type:"prevTaskEnd",id:t},n.endTime={data:r[0]};break;case 2:n.id=ut(),n.startTime={type:"getStartDate",startData:r[0]},n.endTime={data:r[1]};break;case 3:n.id=ut(r[0]),n.startTime={type:"getStartDate",startData:r[1]},n.endTime={data:r[2]};break}return n},"parseData"),Ft,_t,B=[],ue={},Is=c(function(t,a){const i={section:dt,type:dt,processed:!1,manualEndTime:!1,renderEndTime:null,raw:{data:a},task:t,classes:[]},r=Es(_t,a);i.raw.startTime=r.startTime,i.raw.endTime=r.endTime,i.id=r.id,i.prevTaskId=_t,i.active=r.active,i.done=r.done,i.crit=r.crit,i.milestone=r.milestone,i.vert=r.vert,i.order=$t,$t++;const n=B.push(i);_t=i.id,ue[i.id]=n-1},"addTask"),at=c(function(t){const a=ue[t];return B[a]},"findTaskById"),$s=c(function(t,a){const i={section:dt,type:dt,description:t,task:t,classes:[]},r=Ms(Ft,a);i.startTime=r.startTime,i.endTime=r.endTime,i.id=r.id,i.active=r.active,i.done=r.done,i.crit=r.crit,i.milestone=r.milestone,i.vert=r.vert,Ft=i,Dt.push(i)},"addTaskOrg"),re=c(function(){const t=c(function(i){const r=B[i];let n="";switch(B[i].raw.startTime.type){case"prevTaskEnd":{const k=at(r.prevTaskId);r.startTime=k.endTime;break}case"getStartDate":n=Yt(void 0,tt,B[i].raw.startTime.startData),n&&(B[i].startTime=n);break}return B[i].startTime&&(B[i].endTime=le(B[i].startTime,tt,B[i].raw.endTime.data,yt),B[i].endTime&&(B[i].processed=!0,B[i].manualEndTime=j(B[i].raw.endTime.data,"YYYY-MM-DD",!0).isValid(),oe(B[i],tt,kt,mt))),B[i].processed},"compileTask");let a=!0;for(const[i,r]of B.entries())t(i),a=a&&r.processed;return a},"compileTasks"),Ys=c(function(t,a){let i=a;lt().securityLevel!=="loose"&&(i=Le.sanitizeUrl(a)),t.split(",").forEach(function(r){at(r)!==void 0&&(fe(r,()=>{window.open(i,"_self")}),Ot.set(r,i))}),de(t,"clickable")},"setLink"),de=c(function(t,a){t.split(",").forEach(function(i){let r=at(i);r!==void 0&&r.classes.push(a)})},"setClass"),Fs=c(function(t,a,i){if(lt().securityLevel!=="loose"||a===void 0)return;let r=[];if(typeof i=="string"){r=i.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);for(let k=0;k<r.length;k++){let y=r[k].trim();y.startsWith('"')&&y.endsWith('"')&&(y=y.substr(1,y.length-2)),r[k]=y}}r.length===0&&r.push(t),at(t)!==void 0&&fe(t,()=>{Oe.runFunc(a,...r)})},"setClickFun"),fe=c(function(t,a){Nt.push(function(){const i=document.querySelector(`[id="${t}"]`);i!==null&&i.addEventListener("click",function(){a()})},function(){const i=document.querySelector(`[id="${t}-text"]`);i!==null&&i.addEventListener("click",function(){a()})})},"pushFun"),As=c(function(t,a,i){t.split(",").forEach(function(r){Fs(r,a,i)}),de(t,"clickable")},"setClickEvent"),Ls=c(function(t){Nt.forEach(function(a){a(t)})},"bindFunctions"),Ws={getConfig:c(()=>lt().gantt,"getConfig"),clear:es,setDateFormat:cs,getDateFormat:ks,enableInclusiveEndDates:ls,endDatesAreInclusive:us,enableTopAxis:ds,topAxisEnabled:fs,setAxisFormat:ss,getAxisFormat:rs,setTickInterval:is,getTickInterval:ns,setTodayMarker:as,getTodayMarker:os,setAccTitle:ge,getAccTitle:ve,setDiagramTitle:ye,getDiagramTitle:ke,setDisplayMode:hs,getDisplayMode:ms,setAccDescription:me,getAccDescription:he,addSection:xs,getSections:bs,getTasks:ws,addTask:Is,findTaskById:at,addTaskOrg:$s,setIncludes:ys,getIncludes:vs,setExcludes:gs,getExcludes:ps,setClickEvent:As,setLink:Ys,getLinks:Ts,bindFunctions:Ls,parseDuration:ce,isInvalidDate:ae,setWeekday:_s,getWeekday:Ds,setWeekend:Ss};function Ht(t,a,i){let r=!0;for(;r;)r=!1,i.forEach(function(n){const k="^\\s*"+n+"\\s*$",y=new RegExp(k);t[0].match(y)&&(a[n]=!0,t.shift(1),r=!0)})}c(Ht,"getTaskTags");j.extend(Je);var Os=c(function(){nt.debug("Something is calling, setConf, remove the call")},"setConf"),ie={monday:Ye,tuesday:$e,wednesday:Ie,thursday:Ee,friday:Me,saturday:Ce,sunday:Se},Ps=c((t,a)=>{let i=[...t].map(()=>-1/0),r=[...t].sort((k,y)=>k.startTime-y.startTime||k.order-y.order),n=0;for(const k of r)for(let y=0;y<i.length;y++)if(k.startTime>=i[y]){i[y]=k.endTime,k.order=y+a,y>n&&(n=y);break}return n},"getMaxIntersections"),et,Et=1e4,Vs=c(function(t,a,i,r){const n=lt().gantt,k=lt().securityLevel;let y;k==="sandbox"&&(y=gt("#i"+a));const _=k==="sandbox"?gt(y.nodes()[0].contentDocument.body):gt("body"),W=k==="sandbox"?y.nodes()[0].contentDocument:document,A=W.getElementById(a);et=A.parentElement.offsetWidth,et===void 0&&(et=1200),n.useWidth!==void 0&&(et=n.useWidth);const b=r.db.getTasks();let L=[];for(const u of b)L.push(u.type);L=d(L);const V={};let N=2*n.topPadding;if(r.db.getDisplayMode()==="compact"||n.displayMode==="compact"){const u={};for(const g of b)u[g.section]===void 0?u[g.section]=[g]:u[g.section].push(g);let p=0;for(const g of Object.keys(u)){const v=Ps(u[g],p)+1;p+=v,N+=v*(n.barHeight+n.barGap),V[g]=v}}else{N+=b.length*(n.barHeight+n.barGap);for(const u of L)V[u]=b.filter(p=>p.type===u).length}A.setAttribute("viewBox","0 0 "+et+" "+N);const z=_.select(`[id="${a}"]`),M=pe().domain([Te(b,function(u){return u.startTime}),xe(b,function(u){return u.endTime})]).rangeRound([0,et-n.leftPadding-n.rightPadding]);function D(u,p){const g=u.startTime,v=p.startTime;let f=0;return g>v?f=1:g<v&&(f=-1),f}c(D,"taskCompare"),b.sort(D),S(b,et,N),be(z,N,et,n.useMaxWidth),z.append("text").text(r.db.getDiagramTitle()).attr("x",et/2).attr("y",n.titleTopMargin).attr("class","titleText");function S(u,p,g){const v=n.barHeight,f=v+n.barGap,o=n.topPadding,l=n.leftPadding,h=we().domain([0,L.length]).range(["#00B9FA","#F95002"]).interpolate(_e);Y(f,o,l,p,g,u,r.db.getExcludes(),r.db.getIncludes()),q(l,o,p,g),O(u,f,o,l,v,h,p),E(f,o),T(l,o,p,g)}c(S,"makeGantt");function O(u,p,g,v,f,o,l){u.sort((e,w)=>e.vert===w.vert?0:e.vert?1:-1);const m=[...new Set(u.map(e=>e.order))].map(e=>u.find(w=>w.order===e));z.append("g").selectAll("rect").data(m).enter().append("rect").attr("x",0).attr("y",function(e,w){return w=e.order,w*p+g-2}).attr("width",function(){return l-n.rightPadding/2}).attr("height",p).attr("class",function(e){for(const[w,F]of L.entries())if(e.type===F)return"section section"+w%n.numberSectionStyles;return"section section0"}).enter();const x=z.append("g").selectAll("rect").data(u).enter(),s=r.db.getLinks();if(x.append("rect").attr("id",function(e){return e.id}).attr("rx",3).attr("ry",3).attr("x",function(e){return e.milestone?M(e.startTime)+v+.5*(M(e.endTime)-M(e.startTime))-.5*f:M(e.startTime)+v}).attr("y",function(e,w){return w=e.order,e.vert?n.gridLineStartPadding:w*p+g}).attr("width",function(e){return e.milestone?f:e.vert?.08*f:M(e.renderEndTime||e.endTime)-M(e.startTime)}).attr("height",function(e){return e.vert?b.length*(n.barHeight+n.barGap)+n.barHeight*2:f}).attr("transform-origin",function(e,w){return w=e.order,(M(e.startTime)+v+.5*(M(e.endTime)-M(e.startTime))).toString()+"px "+(w*p+g+.5*f).toString()+"px"}).attr("class",function(e){const w="task";let F="";e.classes.length>0&&(F=e.classes.join(" "));let $=0;for(const[G,C]of L.entries())e.type===C&&($=G%n.numberSectionStyles);let I="";return e.active?e.crit?I+=" activeCrit":I=" active":e.done?e.crit?I=" doneCrit":I=" done":e.crit&&(I+=" crit"),I.length===0&&(I=" task"),e.milestone&&(I=" milestone "+I),e.vert&&(I=" vert "+I),I+=$,I+=" "+F,w+I}),x.append("text").attr("id",function(e){return e.id+"-text"}).text(function(e){return e.task}).attr("font-size",n.fontSize).attr("x",function(e){let w=M(e.startTime),F=M(e.renderEndTime||e.endTime);if(e.milestone&&(w+=.5*(M(e.endTime)-M(e.startTime))-.5*f,F=w+f),e.vert)return M(e.startTime)+v;const $=this.getBBox().width;return $>F-w?F+$+1.5*n.leftPadding>l?w+v-5:F+v+5:(F-w)/2+w+v}).attr("y",function(e,w){return e.vert?n.gridLineStartPadding+b.length*(n.barHeight+n.barGap)+60:(w=e.order,w*p+n.barHeight/2+(n.fontSize/2-2)+g)}).attr("text-height",f).attr("class",function(e){const w=M(e.startTime);let F=M(e.endTime);e.milestone&&(F=w+f);const $=this.getBBox().width;let I="";e.classes.length>0&&(I=e.classes.join(" "));let G=0;for(const[Q,st]of L.entries())e.type===st&&(G=Q%n.numberSectionStyles);let C="";return e.active&&(e.crit?C="activeCritText"+G:C="activeText"+G),e.done?e.crit?C=C+" doneCritText"+G:C=C+" doneText"+G:e.crit&&(C=C+" critText"+G),e.milestone&&(C+=" milestoneText"),e.vert&&(C+=" vertText"),$>F-w?F+$+1.5*n.leftPadding>l?I+" taskTextOutsideLeft taskTextOutside"+G+" "+C:I+" taskTextOutsideRight taskTextOutside"+G+" "+C+" width-"+$:I+" taskText taskText"+G+" "+C+" width-"+$}),lt().securityLevel==="sandbox"){let e;e=gt("#i"+a);const w=e.nodes()[0].contentDocument;x.filter(function(F){return s.has(F.id)}).each(function(F){var $=w.querySelector("#"+F.id),I=w.querySelector("#"+F.id+"-text");const G=$.parentNode;var C=w.createElement("a");C.setAttribute("xlink:href",s.get(F.id)),C.setAttribute("target","_top"),G.appendChild(C),C.appendChild($),C.appendChild(I)})}}c(O,"drawRects");function Y(u,p,g,v,f,o,l,h){if(l.length===0&&h.length===0)return;let m,x;for(const{startTime:$,endTime:I}of o)(m===void 0||$<m)&&(m=$),(x===void 0||I>x)&&(x=I);if(!m||!x)return;if(j(x).diff(j(m),"year")>5){nt.warn("The difference between the min and max time is more than 5 years. This will cause performance issues. Skipping drawing exclude days.");return}const s=r.db.getDateFormat(),P=[];let e=null,w=j(m);for(;w.valueOf()<=x;)r.db.isInvalidDate(w,s,l,h)?e?e.end=w:e={start:w,end:w}:e&&(P.push(e),e=null),w=w.add(1,"d");z.append("g").selectAll("rect").data(P).enter().append("rect").attr("id",$=>"exclude-"+$.start.format("YYYY-MM-DD")).attr("x",$=>M($.start.startOf("day"))+g).attr("y",n.gridLineStartPadding).attr("width",$=>M($.end.endOf("day"))-M($.start.startOf("day"))).attr("height",f-p-n.gridLineStartPadding).attr("transform-origin",function($,I){return(M($.start)+g+.5*(M($.end)-M($.start))).toString()+"px "+(I*u+.5*f).toString()+"px"}).attr("class","exclude-range")}c(Y,"drawExcludeDays");function R(u,p,g,v){if(g<=0||u>p)return 1/0;const f=p-u,o=j.duration({[v??"day"]:g}).asMilliseconds();return o<=0?1/0:Math.ceil(f/o)}c(R,"getEstimatedTickCount");function q(u,p,g,v){const f=r.db.getDateFormat(),o=r.db.getAxisFormat();let l;o?l=o:f==="D"?l="%d":l=n.axisFormat??"%Y-%m-%d";let h=De(M).tickSize(-v+p+n.gridLineStartPadding).tickFormat(qt(l));const x=/^([1-9]\d*)(millisecond|second|minute|hour|day|week|month)$/.exec(r.db.getTickInterval()||n.tickInterval);if(x!==null){const s=parseInt(x[1],10);if(isNaN(s)||s<=0)nt.warn(`Invalid tick interval value: "${x[1]}". Skipping custom tick interval.`);else{const P=x[2],e=r.db.getWeekday()||n.weekday,w=M.domain(),F=w[0],$=w[1],I=R(F,$,s,P);if(I>Et)nt.warn(`The tick interval "${s}${P}" would generate ${I} ticks, which exceeds the maximum allowed (${Et}). This may indicate an invalid date or time range. Skipping custom tick interval.`);else switch(P){case"millisecond":h.ticks(Qt.every(s));break;case"second":h.ticks(Zt.every(s));break;case"minute":h.ticks(Ut.every(s));break;case"hour":h.ticks(Xt.every(s));break;case"day":h.ticks(jt.every(s));break;case"week":h.ticks(ie[e].every(s));break;case"month":h.ticks(Gt.every(s));break}}}if(z.append("g").attr("class","grid").attr("transform","translate("+u+", "+(v-50)+")").call(h).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10).attr("dy","1em"),r.db.topAxisEnabled()||n.topAxis){let s=Fe(M).tickSize(-v+p+n.gridLineStartPadding).tickFormat(qt(l));if(x!==null){const P=parseInt(x[1],10);if(isNaN(P)||P<=0)nt.warn(`Invalid tick interval value: "${x[1]}". Skipping custom tick interval.`);else{const e=x[2],w=r.db.getWeekday()||n.weekday,F=M.domain(),$=F[0],I=F[1];if(R($,I,P,e)<=Et)switch(e){case"millisecond":s.ticks(Qt.every(P));break;case"second":s.ticks(Zt.every(P));break;case"minute":s.ticks(Ut.every(P));break;case"hour":s.ticks(Xt.every(P));break;case"day":s.ticks(jt.every(P));break;case"week":s.ticks(ie[w].every(P));break;case"month":s.ticks(Gt.every(P));break}}}z.append("g").attr("class","grid").attr("transform","translate("+u+", "+p+")").call(s).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10)}}c(q,"makeGrid");function E(u,p){let g=0;const v=Object.keys(V).map(f=>[f,V[f]]);z.append("g").selectAll("text").data(v).enter().append(function(f){const o=f[0].split(Ae.lineBreakRegex),l=-(o.length-1)/2,h=W.createElementNS("http://www.w3.org/2000/svg","text");h.setAttribute("dy",l+"em");for(const[m,x]of o.entries()){const s=W.createElementNS("http://www.w3.org/2000/svg","tspan");s.setAttribute("alignment-baseline","central"),s.setAttribute("x","10"),m>0&&s.setAttribute("dy","1em"),s.textContent=x,h.appendChild(s)}return h}).attr("x",10).attr("y",function(f,o){if(o>0)for(let l=0;l<o;l++)return g+=v[o-1][1],f[1]*u/2+g*u+p;else return f[1]*u/2+p}).attr("font-size",n.sectionFontSize).attr("class",function(f){for(const[o,l]of L.entries())if(f[0]===l)return"sectionTitle sectionTitle"+o%n.numberSectionStyles;return"sectionTitle"})}c(E,"vertLabels");function T(u,p,g,v){const f=r.db.getTodayMarker();if(f==="off")return;const o=z.append("g").attr("class","today"),l=new Date,h=o.append("line");h.attr("x1",M(l)+u).attr("x2",M(l)+u).attr("y1",n.titleTopMargin).attr("y2",v-n.titleTopMargin).attr("class","today"),f!==""&&h.attr("style",f.replace(/,/g,";"))}c(T,"drawToday");function d(u){const p={},g=[];for(let v=0,f=u.length;v<f;++v)Object.prototype.hasOwnProperty.call(p,u[v])||(p[u[v]]=!0,g.push(u[v]));return g}c(d,"checkUnique")},"draw"),Ns={setConf:Os,draw:Vs},zs=c(t=>`
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
`,"getStyles"),Rs=zs,Gs={parser:ts,db:Ws,renderer:Ns,styles:Rs};export{Gs as diagram};
