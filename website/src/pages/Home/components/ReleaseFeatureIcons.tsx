import type { SVGProps } from "react";

export type ReleaseFeatureIcon = (
  props: SVGProps<SVGSVGElement>,
) => JSX.Element;

const sharedProps = {
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  strokeWidth: 1.1,
  vectorEffect: "non-scaling-stroke" as const,
};

function Frame({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 120 96" fill="none" {...props}>
      <g {...sharedProps}>{children}</g>
    </svg>
  );
}

export function HubFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <rect x="46" y="25" width="28" height="42" rx="3" />
      <path d="M51 33h18M51 41h18M51 49h18M51 57h18" />
      <path d="M67 33h1M67 41h1M67 49h1M67 57h1" />
      <circle cx="23" cy="25" r="6" />
      <path d="M14 39c1.5-6 5-9 9-9s7.5 3 9 9" />
      <circle cx="97" cy="25" r="6" />
      <path d="M88 39c1.5-6 5-9 9-9s7.5 3 9 9" />
      <circle cx="23" cy="69" r="6" />
      <path d="M14 83c1.5-6 5-9 9-9s7.5 3 9 9" />
      <circle cx="97" cy="69" r="6" />
      <path d="M88 83c1.5-6 5-9 9-9s7.5 3 9 9" />
      <path d="M32 32l14 6M88 32l-14 6M32 67l14-9M88 67l-14-9" />
      <ellipse
        cx="60"
        cy="47"
        rx="54"
        ry="40"
        strokeDasharray="2.5 4"
        opacity=".45"
      />
    </Frame>
  );
}

export function MailFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <rect x="20" y="25" width="76" height="49" rx="3" />
      <path d="M22 29l36 26 36-26M22 71l25-24M94 71L69 47" />
      <path d="M27 20h62M27 79h62" strokeDasharray="2.5 4" opacity=".48" />
      <path d="M102 10c1 6 5 10 11 11-6 1-10 5-11 11-1-6-5-10-11-11 6-1 10-5 11-11z" />
      <circle cx="14" cy="48" r="2" />
      <path d="M8 48h12" strokeDasharray="2 3" opacity=".55" />
    </Frame>
  );
}

export function DataFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <path d="M18 77h86M24 77V16" />
      <path
        d="M24 62h80M24 47h80M24 32h80"
        strokeDasharray="2 4"
        opacity=".4"
      />
      <rect x="34" y="58" width="11" height="19" rx="1" />
      <rect x="55" y="46" width="11" height="31" rx="1" />
      <rect x="76" y="30" width="11" height="47" rx="1" />
      <path d="M29 53l20-17 17 5 28-24" />
      <circle cx="29" cy="53" r="2.5" />
      <circle cx="49" cy="36" r="2.5" />
      <circle cx="66" cy="41" r="2.5" />
      <circle cx="94" cy="17" r="2.5" />
      <path d="M95 11l5 1-1 5" />
      <path d="M15 84h94M15 9v71" strokeDasharray="2.5 4" opacity=".45" />
    </Frame>
  );
}

export function CreatorFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <rect x="18" y="25" width="84" height="51" rx="3" />
      <path d="M18 38h84M29 25l9 13M48 25l9 13M67 25l9 13M86 25l9 13" />
      <path d="M52 48l18 10-18 10V48z" />
      <path d="M27 20v-7h20M93 81v7H73" />
      <path d="M12 13h10M98 87h10" strokeDasharray="2 3" opacity=".5" />
      <path d="M104 8c.8 5 4 8.2 9 9-5 .8-8.2 4-9 9-.8-5-4-8.2-9-9 5-.8 8.2-4 9-9z" />
    </Frame>
  );
}

export function ModelRoutingFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <path d="M45 34l15-9 15 9v18l-15 9-15-9V34z" />
      <path d="M45 34l15 9 15-9M60 43v18" />
      <circle cx="18" cy="19" r="6" />
      <circle cx="102" cy="19" r="6" />
      <circle cx="18" cy="77" r="6" />
      <circle cx="102" cy="77" r="6" />
      <path d="M24 22l21 14M96 22L75 36M24 74l24-18M96 74L72 56" />
      <path d="M32 11h56M32 85h56" strokeDasharray="2.5 4" opacity=".45" />
      <path d="M14 19h8M98 19h8M14 77h8M98 77h8" opacity=".65" />
      <circle cx="60" cy="43" r="2.5" />
    </Frame>
  );
}

export function BackgroundWorkFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <circle cx="53" cy="47" r="30" />
      <circle cx="53" cy="47" r="37" strokeDasharray="2.5 4" opacity=".45" />
      <path d="M53 24v23l15 9" />
      <circle cx="53" cy="47" r="2.5" />
      <path d="M53 17v6M32 26l4 5M23 47h7M32 68l4-5M74 26l-4 5" />
      <path d="M83 22h14v14M97 22L84 35" />
      <circle cx="92" cy="70" r="14" />
      <path d="M84 70l5 5 10-12" />
    </Frame>
  );
}

export function ExtensionsFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <path d="M22 20h32v22H22zM66 20h32v22H66zM22 54h32v22H22zM66 54h32v22H66z" />
      <rect x="28" y="26" width="20" height="10" rx="2" />
      <path d="M73 36v-6h5l4-4 4 4h5v6M31 65h14M38 59v12" />
      <path d="M73 61l18 8M91 61l-18 8" />
      <circle cx="82" cy="65" r="2" />
      <path
        d="M15 13h42M63 83h42M15 83V50M105 46V13"
        strokeDasharray="2.5 4"
        opacity=".45"
      />
      <path d="M15 20h4M101 76h4" />
    </Frame>
  );
}

export function ReliabilityFeatureIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Frame {...props}>
      <path d="M60 12c12 8 23 10 34 11v22c0 18-11 30-34 39-23-9-34-21-34-39V23c11-1 22-3 34-11z" />
      <path
        d="M60 20c9 5 17 7 26 8v17c0 13-8 23-26 31-18-8-26-18-26-31V28c9-1 17-3 26-8z"
        opacity=".55"
      />
      <path d="M42 50h9l5-10 8 20 6-10h10" />
      <circle cx="42" cy="50" r="2" />
      <circle cx="80" cy="50" r="2" />
      <path
        d="M17 19C30 7 44 4 60 4s30 3 43 15M17 73c11 12 26 18 43 20 17-2 32-8 43-20"
        strokeDasharray="2.5 4"
        opacity=".45"
      />
    </Frame>
  );
}
