/**
 * Tests for API utilities.
 */

import { describe, it, expect } from 'vitest';
import { isAbortError } from '../api';

describe('isAbortError', () => {
  it('returns true for AbortError', () => {
    const controller = new AbortController();
    controller.abort();

    // Create an error that mimics fetch abort
    const error = new DOMException('The operation was aborted', 'AbortError');

    expect(isAbortError(error)).toBe(true);
  });

  it('returns true for Error with name AbortError', () => {
    const error = new Error('Request cancelled');
    error.name = 'AbortError';

    expect(isAbortError(error)).toBe(true);
  });

  it('returns false for regular Error', () => {
    const error = new Error('Something went wrong');

    expect(isAbortError(error)).toBe(false);
  });

  it('returns false for TypeError', () => {
    const error = new TypeError('Network failure');

    expect(isAbortError(error)).toBe(false);
  });

  it('returns false for null', () => {
    expect(isAbortError(null)).toBe(false);
  });

  it('returns false for undefined', () => {
    expect(isAbortError(undefined)).toBe(false);
  });

  it('returns false for non-Error objects', () => {
    expect(isAbortError({ message: 'error' })).toBe(false);
    expect(isAbortError('error string')).toBe(false);
    expect(isAbortError(42)).toBe(false);
  });

  it('returns false for Error subclasses with different names', () => {
    class CustomError extends Error {
      constructor() {
        super('Custom error');
        this.name = 'CustomError';
      }
    }

    expect(isAbortError(new CustomError())).toBe(false);
  });
});
