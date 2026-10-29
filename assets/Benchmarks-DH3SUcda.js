import{c as n,u,j as e,L as r}from"./index-DlrnxKdg.js";/* empty css              */import{A as s}from"./arrow-left-BfpvPXgd.js";import{S as m}from"./search-DAAkR6K4.js";import"./runtime-CqkleIqs.js";/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const t=n("ArrowUpRight",[["path",{d:"M7 7h10v10",key:"1tivn9"}],["path",{d:"M7 17 17 7",key:"1vkiza"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=n("CodeXml",[["path",{d:"m18 16 4-4-4-4",key:"1inbqp"}],["path",{d:"m6 8-4 4 4 4",key:"15zrgr"}],["path",{d:"m14.5 4-5 16",key:"e7oirm"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x=n("FileSpreadsheet",[["path",{d:"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z",key:"1rqfz7"}],["path",{d:"M14 2v4a2 2 0 0 0 2 2h4",key:"tnqrlb"}],["path",{d:"M8 13h2",key:"yr2amv"}],["path",{d:"M14 13h2",key:"un5t4a"}],["path",{d:"M8 17h2",key:"2yhykz"}],["path",{d:"M14 17h2",key:"10kma7"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const g=n("Workflow",[["rect",{width:"8",height:"8",x:"3",y:"3",rx:"2",key:"by2w9f"}],["path",{d:"M7 11v4a2 2 0 0 0 2 2h4",key:"xkn7yn"}],["rect",{width:"8",height:"8",x:"13",y:"13",rx:"2",key:"1cgmvn"}]]),k=[{id:"gaia",name:"GAIA",domain:"research",count:165,Icon:m,url:"https://huggingface.co/datasets/gaia-benchmark/GAIA"},{id:"spreadsheetbench-verified",name:"SpreadsheetBench Verified",domain:"office",count:400,Icon:x,url:"https://spreadsheetbench.github.io/"},{id:"swebench-verified",name:"SWE-bench Verified",domain:"coding",count:500,Icon:p,url:"https://openai.com/index/introducing-swe-bench-verified/"},{id:"pawbench",name:"PawBench",domain:"general",count:150,Icon:g,url:"https://agentscope-ai.github.io/PawBench/"}];function w(){const{t:a}=u("evaluation");return e.jsxs("main",{className:"evaluation-page evaluation-guide",children:[e.jsxs(r,{to:"/evaluation",className:"evaluation-back",children:[e.jsx(s,{size:16}),a("back")]}),e.jsxs("header",{className:"evaluation-guide-header",children:[e.jsx("h1",{children:a("guideTitle")}),e.jsx("p",{children:a("guideIntro")})]}),e.jsx("div",{className:"evaluation-benchmark-grid",children:k.map(({id:i,name:c,domain:d,count:h,Icon:o,url:l})=>e.jsxs("article",{id:i,className:"evaluation-benchmark-card",children:[e.jsxs("header",{children:[e.jsx(o,{size:24,strokeWidth:1.75}),e.jsx("span",{children:a(`domains.${d}`)})]}),e.jsx("h2",{children:c}),e.jsxs("div",{className:"evaluation-benchmark-scale",children:[e.jsx("strong",{children:h}),a("tasks")]}),e.jsx("p",{children:a(`guideBenchmarks.${i}.purpose`)}),e.jsxs("dl",{children:[e.jsx("dt",{children:a("guideScope")}),e.jsx("dd",{children:a(`guideBenchmarks.${i}.scope`)}),e.jsx("dt",{children:a("guideScoring")}),e.jsx("dd",{children:a(`guideBenchmarks.${i}.scoring`)})]}),e.jsxs("a",{href:l,target:"_blank",rel:"noopener noreferrer",children:[a("officialSource"),e.jsx(t,{size:16})]})]},i))}),e.jsxs("section",{className:"evaluation-guide-method",children:[e.jsx("h2",{children:a("guideCompareTitle")}),e.jsxs("div",{children:[e.jsx("p",{children:a("guideCompare")}),e.jsx("p",{children:a("guideMetrics")})]})]}),e.jsxs("section",{className:"evaluation-guide-method evaluation-guide-future",children:[e.jsx("h2",{children:a("guideFutureTitle")}),e.jsxs("div",{children:[e.jsx("p",{children:a("guideFuture")}),e.jsxs("a",{href:"https://platform.agentscope.io/community",target:"_blank",rel:"noopener noreferrer",children:[a("guideCommunity"),e.jsx(t,{size:16})]})]})]}),e.jsxs(r,{to:"/evaluation",className:"evaluation-back",children:[e.jsx(s,{size:16}),a("back")]})]})}export{w as default};
