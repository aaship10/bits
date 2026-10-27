// Inline icon set, 1.5px stroke, 16px grid. Replaces emoji/glyph icons.
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' };

const Svg = ({ children, size = 16, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" focusable="false" {...rest}>
    {children}
  </svg>
);

export const ArrowRight = (p) => (
  <Svg {...p}>
    <path d="M3 8h10M9 4l4 4-4 4" {...P} />
  </Svg>
);
export const ArrowDown = (p) => (
  <Svg {...p}>
    <path d="M8 3v10M4 9l4 4 4-4" {...P} />
  </Svg>
);
export const ArrowUpRight = (p) => (
  <Svg {...p}>
    <path d="M5 11l6-6M6 5h5v5" {...P} />
  </Svg>
);
export const Alert = (p) => (
  <Svg {...p}>
    <path d="M8 2.2 14.2 13H1.8L8 2.2Z" {...P} />
    <path d="M8 6.5v3M8 11.3v.1" {...P} />
  </Svg>
);
export const Play = (p) => (
  <Svg {...p}>
    <path d="M5 3.2v9.6L12.5 8 5 3.2Z" fill="currentColor" stroke="none" />
  </Svg>
);
export const Pause = (p) => (
  <Svg {...p}>
    <path d="M5 3.5v9M11 3.5v9" {...P} strokeWidth="2" />
  </Svg>
);
export const Prev = (p) => (
  <Svg {...p}>
    <path d="M10 3.5 5.5 8l4.5 4.5" {...P} />
  </Svg>
);
export const Next = (p) => (
  <Svg {...p}>
    <path d="M6 3.5 10.5 8 6 12.5" {...P} />
  </Svg>
);
export const Plus = (p) => (
  <Svg {...p}>
    <path d="M8 3v10M3 8h10" {...P} />
  </Svg>
);
export const Close = (p) => (
  <Svg {...p}>
    <path d="M4 4l8 8M12 4l-8 8" {...P} />
  </Svg>
);
export const Upload = (p) => (
  <Svg {...p}>
    <path d="M8 11V3M4.5 6.5 8 3l3.5 3.5M3 13h10" {...P} />
  </Svg>
);
export const Info = (p) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6" {...P} />
    <path d="M8 7.2v3.6M8 5.1v.1" {...P} />
  </Svg>
);

// Mode markers: circle = main grid, diamond = renewable storage.
export const MarkMain = ({ size = 10, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden="true" {...rest}>
    <circle cx="5" cy="5" r="4" fill="currentColor" />
  </svg>
);
export const MarkStorage = ({ size = 10, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden="true" {...rest}>
    <path d="M5 .5 9.5 5 5 9.5.5 5 5 .5Z" fill="currentColor" />
  </svg>
);
