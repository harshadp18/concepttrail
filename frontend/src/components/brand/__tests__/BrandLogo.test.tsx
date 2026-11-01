import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { BrandLogo } from '../BrandLogo';

describe('BrandLogo Component (Image 38 Single Source of Truth)', () => {
  it('renders the official ConceptTrail logo artwork', () => {
    render(
      <BrowserRouter>
        <BrandLogo variant="full" />
      </BrowserRouter>
    );

    const logoImg = screen.getByAltText('ConceptTrail');
    expect(logoImg).toBeInTheDocument();
    expect(logoImg).toHaveAttribute('src');
    expect(logoImg.getAttribute('src')).toContain('concepttrail-logo');
  });

  it('renders with accessible link when linkTo prop is supplied', () => {
    render(
      <BrowserRouter>
        <BrandLogo variant="full" linkTo="/" />
      </BrowserRouter>
    );

    const link = screen.getByRole('link', { name: /ConceptTrail/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/');
  });

  it('applies correct sizing classes for different variants', () => {
    const { container: smContainer } = render(
      <BrowserRouter>
        <BrandLogo size="sm" />
      </BrowserRouter>
    );
    expect(smContainer.querySelector('img')).toHaveClass('h-8');

    const { container: lgContainer } = render(
      <BrowserRouter>
        <BrandLogo size="lg" />
      </BrowserRouter>
    );
    expect(lgContainer.querySelector('img')).toHaveClass('h-12');
  });
});
