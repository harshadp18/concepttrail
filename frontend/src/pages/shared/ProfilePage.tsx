import React, { useState } from 'react';
import * as Switch from '@radix-ui/react-switch';
import { LogOut } from 'lucide-react';
import { classLabel, personName, useAuth } from '@/context/AuthContext';
import { Card, cx, PageHeader } from '@/components/ui/primitives';

function read(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // preferences then last only for this visit
  }
}

const Toggle: React.FC<{ id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void }> = ({ id, label, hint, checked, onChange }) => (
  <div className="flex items-start justify-between gap-4 py-3">
    <label htmlFor={id} className="min-w-0">
      <span className="block text-sm font-semibold text-ctText-primary">{label}</span>
      <span className="text-xs text-ctText-muted">{hint}</span>
    </label>
    <Switch.Root
      id={id}
      checked={checked}
      onCheckedChange={onChange}
      className="relative h-6 w-11 shrink-0 rounded-full bg-surface-border transition-colors data-[state=checked]:bg-brand-500 focus-ring"
    >
      <Switch.Thumb className="block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[22px]" />
    </Switch.Root>
  </div>
);

/** Account details come from GET /me; display preferences are stored on this device only. */
export const ProfilePage: React.FC = () => {
  const { user, logout } = useAuth();
  const [size, setSize] = useState(read('concepttrail_text_size', 'default'));
  const [spacing, setSpacing] = useState(read('concepttrail_line_spacing', 'false') === 'true');
  const [contrast, setContrast] = useState(read('concepttrail_high_contrast', 'false') === 'true');
  if (!user) return null;
  const classes = user.role === 'student' ? user.enrolled_classrooms : user.assigned_classrooms;

  const applySize = (v: string) => {
    setSize(v);
    write('concepttrail_text_size', v);
    if (v === 'default') document.documentElement.removeAttribute('data-text-size');
    else document.documentElement.setAttribute('data-text-size', v);
  };

  return (
    <div>
      <PageHeader title="Profile and preferences" />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <h2 className="t-section">Account</h2>
          <dl className="mt-4 divide-y divide-surface-border-subtle text-sm">
            {[
              ['Name', personName(user) || '—'],
              [user.role === 'student' ? 'Username' : 'School email', user.login_identifier],
              ['Role', user.role === 'student' ? 'Student' : 'Teacher'],
              [user.role === 'student' ? 'Class' : 'Assigned classes', classes.length ? classes.map((c) => classLabel(c)).join(', ') : 'None'],
              ['School', classes[0]?.school_label ?? '—'],
              ['Session', classes[0]?.academic_session ?? '—'],
            ].map(([k, v]) => (
              <div key={k} className="flex flex-col gap-0.5 py-2.5 sm:flex-row sm:justify-between sm:gap-4">
                <dt className="text-ctText-muted">{k}</dt>
                <dd className="break-words font-semibold text-ctText-primary sm:text-right">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-xs text-ctText-muted">
            Your school manages these details. To change your {user.role === 'student' ? 'PIN' : 'password'} or class, contact your school
            administrator.
          </p>
          <button type="button" onClick={() => logout('/login')} className="btn btn-danger mt-5">
            <LogOut size={15} aria-hidden /> Sign out
          </button>
        </Card>
        <Card>
          <h2 className="t-section">Reading and display</h2>
          <p className="mt-1 text-xs text-ctText-muted">Saved on this device only.</p>
          <div className="mt-4">
            <p className="text-sm font-semibold text-ctText-primary" id="text-size">
              Text size
            </p>
            <div role="radiogroup" aria-labelledby="text-size" className="mt-2 grid grid-cols-3 gap-2">
              {[
                ['default', 'Standard'],
                ['medium', 'Larger'],
                ['large', 'Largest'],
              ].map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={size === v}
                  onClick={() => applySize(v)}
                  className={cx('btn btn-sm', size === v ? 'bg-brand-700 text-white' : 'btn-secondary')}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3 divide-y divide-surface-border-subtle">
            <Toggle
              id="spacing"
              label="Extra line spacing"
              hint="More space between lines of text."
              checked={spacing}
              onChange={(v) => {
                setSpacing(v);
                write('concepttrail_line_spacing', String(v));
                document.body.classList.toggle('accessibility-line-spacing', v);
              }}
            />
            <Toggle
              id="contrast"
              label="Higher contrast"
              hint="Darker secondary text."
              checked={contrast}
              onChange={(v) => {
                setContrast(v);
                write('concepttrail_high_contrast', String(v));
                document.body.classList.toggle('accessibility-high-contrast', v);
              }}
            />
          </div>
          <p className="mt-3 text-xs text-ctText-muted">Animations follow your device's “reduce motion” setting.</p>
        </Card>
      </div>
    </div>
  );
};

export default ProfilePage;
