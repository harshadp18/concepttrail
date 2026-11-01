import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LandingPage } from '@/pages/public/LandingPage';

describe('LandingPage', () => {
  it('has no search, no 3D claims and no class-specific marketing copy', () => {
    const { container } = render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    );
    const text = container.textContent ?? '';
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(screen.queryByLabelText(/search/i)).toBeNull();
    expect(text).not.toMatch(/\b3D\b/i);
    expect(text).not.toMatch(/Class 8A/);
    expect(text).toMatch(/Get clear, real-time insights into class progress and learning needs/);
  });

  it('gives the three calls to action different destinations', () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login');
    expect(screen.getByRole('link', { name: 'Get started' })).toHaveAttribute('href', '#get-started');
    expect(screen.getByRole('link', { name: /Explore the student journey/ })).toHaveAttribute('href', '#how-it-works');
  });
});
