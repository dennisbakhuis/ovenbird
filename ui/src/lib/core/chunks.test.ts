import { describe, expect, it, vi } from 'vitest';
import { retrying } from './chunks';

describe('retrying', () => {
  it('shares one load between calls', async () => {
    const load = vi.fn(() => Promise.resolve('page'));
    const get = retrying(load, () => undefined);
    expect(await get()).toBe('page');
    expect(await get()).toBe('page');
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('tries again after a failed load instead of remembering the failure', async () => {
    const load = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new TypeError('Importing a module script failed.'))
      .mockResolvedValueOnce('page');
    const onError = vi.fn();
    const get = retrying(load, onError);
    await expect(get()).rejects.toThrow('Importing a module script failed.');
    expect(onError).toHaveBeenCalledTimes(1);
    expect(await get()).toBe('page');
    expect(load).toHaveBeenCalledTimes(2);
  });
});
