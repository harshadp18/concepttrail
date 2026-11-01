import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/context/AuthContext';
import { LoginPage } from '@/pages/auth/LoginPage';

function setup() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('LoginPage', () => {
  it('shows role-specific messaging and fields, without pre-filled credentials', async () => {
    setup();
    expect(screen.getByRole('heading', { name: 'Learn, practise and grow.' })).toBeInTheDocument();
    expect(screen.getByLabelText('Username')).toHaveValue('');
    expect(screen.getByLabelText('8-digit PIN')).toHaveValue('');
    await userEvent.click(screen.getByRole('tab', { name: /teacher/i }));
    expect(await screen.findByRole('heading', { name: 'See progress. Support every learner.' })).toBeInTheDocument();
    expect(screen.queryByText('Learn, practise and grow.')).toBeNull();
    expect(screen.getByLabelText('School email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('keeps what was typed when switching roles and back', async () => {
    setup();
    await userEvent.type(screen.getByLabelText('Username'), 'stu.one');
    await userEvent.click(screen.getByRole('tab', { name: /teacher/i }));
    await userEvent.type(screen.getByLabelText('School email'), 't@school.example');
    await userEvent.click(screen.getByRole('tab', { name: /student/i }));
    expect(screen.getByLabelText('Username')).toHaveValue('stu.one');
  });

  it('accepts digits only for the PIN and explains an incomplete PIN', async () => {
    setup();
    const pin = screen.getByLabelText('8-digit PIN');
    await userEvent.type(pin, '12ab34');
    expect(pin).toHaveValue('1234');
    expect(screen.getByText(/Your PIN has 8 digits \(4 entered\)/)).toBeInTheDocument();
  });
});
