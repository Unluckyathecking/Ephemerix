import { test } from 'node:test';
import assert from 'node:assert/strict';
import { countsVisits } from '../js/visits.js';

test('visits are counted on the hosted site and nowhere else', () => {
  assert.equal(countsVisits('ephemerix.vercel.app'), true);
  assert.equal(countsVisits('localhost'), false);
  assert.equal(countsVisits('127.0.0.1'), false);
  assert.equal(countsVisits('example.org'), false);
});
