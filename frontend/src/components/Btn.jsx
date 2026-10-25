import { ArrowRight } from './icons';

// Text label plus a square icon block, as on the reference site.
//   variant: "solid" (dark square), "line" (outlined, no icon block), "text" (underlined)
export default function Btn({ as: Tag = 'button', variant = 'solid', size, icon = <ArrowRight />, children, className = '', ...rest }) {
  const cls = `btn btn--${variant} ${size ? `btn--${size}` : ''} ${className}`.trim();
  return (
    <Tag className={cls} {...(Tag === 'button' ? { type: 'button' } : {})} {...rest}>
      <span className="btn__label">{children}</span>
      {variant === 'solid' && icon && <span className="btn__icon">{icon}</span>}
    </Tag>
  );
}
