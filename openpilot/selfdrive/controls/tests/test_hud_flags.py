import unittest
from types import SimpleNamespace

from openpilot.selfdrive.controls.controlsd import lane_flags_from_probs, lead_follow_status


class TestLaneFlagsFromProbs(unittest.TestCase):
  def test_flags_off_stock(self):
    left_v, right_v = lane_flags_from_probs([], False)
    self.assertTrue(left_v and right_v)

  def test_missing_probs_grey(self):
    left_v, right_v = lane_flags_from_probs([], True)
    self.assertFalse(left_v or right_v)

  def test_unsure_side_grey(self):
    left_v, right_v = lane_flags_from_probs([1.0, 0.9, 0.4], True)
    self.assertTrue(left_v)
    self.assertFalse(right_v)


class TestLeadFollowStatus(unittest.TestCase):
  def test_no_lead(self):
    lead = SimpleNamespace(present=False, dRel=0.0, vLead=0.0)
    self.assertEqual(lead_follow_status(lead, 1), 0)

  def test_within_gap(self):
    lead = SimpleNamespace(present=True, dRel=30.0, vLead=20.0)
    self.assertEqual(lead_follow_status(lead, 1), 1)

  def test_closer_than_gap(self):
    lead = SimpleNamespace(present=True, dRel=20.0, vLead=20.0)
    self.assertEqual(lead_follow_status(lead, 1), 2)

  def test_too_close(self):
    lead = SimpleNamespace(present=True, dRel=10.0, vLead=20.0)
    self.assertEqual(lead_follow_status(lead, 0), 3)

  def test_standstill_lead(self):
    lead = SimpleNamespace(present=True, dRel=2.0, vLead=0.0)
    self.assertEqual(lead_follow_status(lead, 1), 1)


if __name__ == "__main__":
  unittest.main()
