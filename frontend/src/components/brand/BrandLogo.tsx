import React from 'react';
import { Link } from 'react-router-dom';
import logoFull from '@/assets/brand/concepttrail-logo.png';
import logoMark from '@/assets/brand/concepttrail-mark.png';

/**
 * The official ConceptTrail logo. Both images are cut from the supplied artwork
 * (src/assets/concepttrail-logo.png) with the surrounding background trimmed; the artwork itself
 * is never redrawn or recoloured. Proportions are preserved with `w-auto`.
 */
export interface BrandLogoProps {
  variant?: 'full' | 'mark' | 'responsive';
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'hero';
  className?: string;
  linkTo?: string | null;
}

const heights = {
  xs: 'h-6',
  sm: 'h-8',
  md: 'h-10',
  lg: 'h-12',
  xl: 'h-14',
  hero: 'h-16 md:h-20',
};

export const BrandLogo: React.FC<BrandLogoProps> = ({ variant = 'full', size = 'md', className = '', linkTo = '/' }) => {
  const h = heights[size];
  const image =
    variant === 'responsive' ? (
      <>
        <img src={logoMark} alt="ConceptTrail" className={`${h} w-auto select-none sm:hidden`} />
        <img src={logoFull} alt="ConceptTrail" className={`${h} w-auto select-none hidden sm:block`} />
      </>
    ) : (
      <img
        src={variant === 'mark' ? logoMark : logoFull}
        alt="ConceptTrail"
        className={`${h} w-auto select-none`}
        draggable={false}
      />
    );
  const content = <span className={`inline-flex items-center ${className}`}>{image}</span>;
  if (!linkTo) return content;
  return (
    <Link to={linkTo} className="inline-flex items-center rounded-lg p-1 -m-1 focus-ring" aria-label="ConceptTrail home">
      {content}
    </Link>
  );
};

export default BrandLogo;
