import{_ as b,D as m,H as B,e as C,l as w,b as S,a as D,p as T,q as E,g as F,s as P,E as z,F as A,y as W}from"./index-CoDRBu_q.js";import{p as _}from"./chunk-4BX2VUAB-C--JJvqJ.js";import{p as N}from"./treemap-KMMF4GRG-Cj6CNOLG.js";import"./min-BznvmHxw.js";import"./_baseUniq-BKT3Rr0K.js";var L=z.packet,u,v=(u=class{constructor(){this.packet=[],this.setAccTitle=S,this.getAccTitle=D,this.setDiagramTitle=T,this.getDiagramTitle=E,this.getAccDescription=F,this.setAccDescription=P}getConfig(){const t=m({...L,...A().packet});return t.showBits&&(t.paddingY+=10),t}getPacket(){return this.packet}pushWord(t){t.length>0&&this.packet.push(t)}clear(){W(),this.packet=[]}},b(u,"PacketDB"),u),M=1e4,Y=b((e,t)=>{_(e,t);let s=-1,r=[],n=1;const{bitsPerRow:l}=t.getConfig();for(let{start:a,end:i,bits:d,label:c}of e.blocks){if(a!==void 0&&i!==void 0&&i<a)throw new Error(`Packet block ${a} - ${i} is invalid. End must be greater than start.`);if(a??(a=s+1),a!==s+1)throw new Error(`Packet block ${a} - ${i??a} is not contiguous. It should start from ${s+1}.`);if(d===0)throw new Error(`Packet block ${a} is invalid. Cannot have a zero bit field.`);for(i??(i=a+(d??1)-1),d??(d=i-a+1),s=i,w.debug(`Packet block ${a} - ${s} with label ${c}`);r.length<=l+1&&t.getPacket().length<M;){const[p,o]=H({start:a,end:i,bits:d,label:c},n,l);if(r.push(p),p.end+1===n*l&&(t.pushWord(r),r=[],n++),!o)break;({start:a,end:i,bits:d,label:c}=o)}}t.pushWord(r)},"populate"),H=b((e,t,s)=>{if(e.start===void 0)throw new Error("start should have been set during first phase");if(e.end===void 0)throw new Error("end should have been set during first phase");if(e.start>e.end)throw new Error(`Block start ${e.start} is greater than block end ${e.end}.`);if(e.end+1<=t*s)return[e,void 0];const r=t*s-1,n=t*s;return[{start:e.start,end:r,label:e.label,bits:r-e.start},{start:n,end:e.end,label:e.label,bits:e.end-n}]},"getNextFittingBlock"),x={parser:{yy:void 0},parse:b(async e=>{var r;const t=await N("packet",e),s=(r=x.parser)==null?void 0:r.yy;if(!(s instanceof v))throw new Error("parser.parser?.yy was not a PacketDB. This is due to a bug within Mermaid, please report this issue at https://github.com/mermaid-js/mermaid/issues.");w.debug(t),Y(t,s)},"parse")},I=b((e,t,s,r)=>{const n=r.db,l=n.getConfig(),{rowHeight:a,paddingY:i,bitWidth:d,bitsPerRow:c}=l,p=n.getPacket(),o=n.getDiagramTitle(),h=a+i,g=h*(p.length+1)-(o?0:a),k=d*c+2,f=B(t);f.attr("viewbox",`0 0 ${k} ${g}`),C(f,g,k,l.useMaxWidth);for(const[y,$]of p.entries())O(f,$,y,l);f.append("text").text(o).attr("x",k/2).attr("y",g-h/2).attr("dominant-baseline","middle").attr("text-anchor","middle").attr("class","packetTitle")},"draw"),O=b((e,t,s,{rowHeight:r,paddingX:n,paddingY:l,bitWidth:a,bitsPerRow:i,showBits:d})=>{const c=e.append("g"),p=s*(r+l)+l;for(const o of t){const h=o.start%i*a+1,g=(o.end-o.start+1)*a-n;if(c.append("rect").attr("x",h).attr("y",p).attr("width",g).attr("height",r).attr("class","packetBlock"),c.append("text").attr("x",h+g/2).attr("y",p+r/2).attr("class","packetLabel").attr("dominant-baseline","middle").attr("text-anchor","middle").text(o.label),!d)continue;const k=o.end===o.start,f=p-2;c.append("text").attr("x",h+(k?g/2:0)).attr("y",f).attr("class","packetByte start").attr("dominant-baseline","auto").attr("text-anchor",k?"middle":"start").text(o.start),k||c.append("text").attr("x",h+g).attr("y",f).attr("class","packetByte end").attr("dominant-baseline","auto").attr("text-anchor","end").text(o.end)}},"drawWord"),j={draw:I},q={byteFontSize:"10px",startByteColor:"black",endByteColor:"black",labelColor:"black",labelFontSize:"12px",titleColor:"black",titleFontSize:"14px",blockStrokeColor:"black",blockStrokeWidth:"1",blockFillColor:"#efefef"},G=b(({packet:e}={})=>{const t=m(q,e);return`
	.packetByte {
		font-size: ${t.byteFontSize};
	}
	.packetByte.start {
		fill: ${t.startByteColor};
	}
	.packetByte.end {
		fill: ${t.endByteColor};
	}
	.packetLabel {
		fill: ${t.labelColor};
		font-size: ${t.labelFontSize};
	}
	.packetTitle {
		fill: ${t.titleColor};
		font-size: ${t.titleFontSize};
	}
	.packetBlock {
		stroke: ${t.blockStrokeColor};
		stroke-width: ${t.blockStrokeWidth};
		fill: ${t.blockFillColor};
	}
	`},"styles"),Q={parser:x,get db(){return new v},renderer:j,styles:G};export{Q as diagram};
