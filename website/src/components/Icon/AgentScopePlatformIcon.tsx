import React from "react";
import type { IconProps } from "./types";

export const AgentScopePlatformIcon: React.FC<IconProps> = ({
  size = 18,
  className = "",
}) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      xmlnsXlink="http://www.w3.org/1999/xlink"
      fill="none"
      width={size}
      height={(size * 14.148) / 15.631}
      viewBox="0 0 15.630859375 14.1484375"
      className={`inline-block ${className}`}
      aria-hidden
    >
      <defs>
        <linearGradient x1="0" y1="0" x2="1.006" y2="0.023" id="as_p_g0">
          <stop offset="0%" stopColor="#FEAF30" />
          <stop offset="100%" stopColor="#F74B0E" />
        </linearGradient>
        <linearGradient x1="0" y1="0.255" x2="0.888" y2="0.758" id="as_p_g1">
          <stop offset="0%" stopColor="#F53807" />
          <stop offset="100%" stopColor="#FDAE2F" />
        </linearGradient>
        <linearGradient
          x1="1.097"
          y1="0.316"
          x2="0.433"
          y2="0.397"
          id="as_p_g2"
        >
          <stop offset="0%" stopColor="#FA410C" />
          <stop offset="100%" stopColor="#FDB52D" />
        </linearGradient>
        <linearGradient
          x1="-0.572"
          y1="0.338"
          x2="-0.05"
          y2="1.58"
          id="as_p_g3"
        >
          <stop offset="0%" stopColor="#FDAE2C" />
          <stop offset="100%" stopColor="#F8410E" />
        </linearGradient>
      </defs>
      <path
        d="M3.489,3.356L1.521,0L11.359,0C12.288,0.142,13.12,0.506,13.673,1.042L3.489,3.356Z"
        fill="url(#as_p_g0)"
      />
      <path
        d={
          "M10.897,3.351L3.5,3.355L13.674,1.036C17.377,3.929,15.294,9.137," +
          "11.822,9.832L6.194,9.832L6.935,6.702L11.044,6.702L11.044,6.701" +
          "Q11.127,6.701,11.209,6.692Q11.291,6.684,11.372,6.668" +
          "Q11.452,6.652,11.531,6.628Q11.61,6.604,11.686,6.572" +
          "Q11.762,6.541,11.835,6.502Q11.907,6.463,11.976,6.417" +
          "Q12.044,6.371,12.108,6.319Q12.171,6.267,12.23,6.208" +
          "Q12.288,6.15,12.34,6.086Q12.392,6.023,12.438,5.954" +
          "Q12.484,5.886,12.523,5.813Q12.561,5.74,12.593,5.664" +
          "Q12.624,5.588,12.648,5.509Q12.672,5.43,12.688,5.35" +
          "Q12.704,5.269,12.712,5.187Q12.72,5.105,12.72,5.023" +
          "Q12.72,4.947,12.714,4.872Q12.707,4.796,12.693,4.722" +
          "Q12.68,4.648,12.66,4.575Q12.639,4.502,12.613,4.431" +
          "Q12.586,4.361,12.553,4.293Q12.52,4.225,12.482,4.16" +
          "Q12.443,4.095,12.398,4.034Q12.354,3.973,12.304,3.916" +
          "Q12.254,3.859,12.199,3.807Q12.144,3.755,12.085,3.708" +
          "Q12.026,3.661,11.963,3.62Q11.9,3.578,11.833,3.542" +
          "Q11.766,3.507,11.697,3.477Q11.627,3.448,11.555,3.425" +
          "Q11.483,3.402,11.41,3.385Q11.336,3.369,11.261,3.359" +
          "C11.255,3.356,11.249,3.353,11.243,3.351L11.185,3.351" +
          "Q11.114,3.344,11.042,3.344Q10.97,3.344,10.897,3.351Z"
        }
        fillRule="evenodd"
        fill="url(#as_p_g1)"
      />
      <path
        d="M7.365,4.072L10.854,14.149L14.731,14.149L11.219,4.072L7.365,4.072Z"
        fill="url(#as_p_g2)"
        transform="matrix(-1,0,0,1,14.73,0)"
      />
      <path
        d="M3.512,4.072L7.366,4.072L3.875,14.149L3.512,4.072Z"
        fill="url(#as_p_g3)"
      />
    </svg>
  );
};

export default AgentScopePlatformIcon;
