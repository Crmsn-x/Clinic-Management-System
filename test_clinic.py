import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from clinic import *


class ClinicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "actions.log"
        self.log = AppointmentLog(self.path)
        self.log.__enter__()
        self.addCleanup(self.log.__exit__, None, None, None)
        self.clock = ManualClock()

    def clinic(self, p):
        c = Clinic(p, self.clock, self.log)
        c.add_staff(Doctor(id=1, name="D", p=p))
        c.add_staff(Nurse(id=2, name="N", p=p))
        c.add_staff(Pharmacist(id=3, name="P", p=p))
        for patient in [Patient(id=10, name="A"),
                        StudentPatient(id=11, name="B", emergency=True),
                        StaffMemberPatient(id=12, name="C"),
                        VisitorPatient(id=13, name="D")]:
            c.add_patient(patient)
        return c

    def test_validation_and_abstract_classes(self):
        for name, id in [(" ", 1), ("A", 0), ("A", -1), ("A", 1.5), ("A", True)]:
            with self.assertRaises(ValueError): Patient(name=name, id=id)
        with self.assertRaises(TypeError): Person(name="A", id=1)
        with self.assertRaises(TypeError): Staff(name="A", id=1, p=0)
        with self.assertRaises(ValueError): ManualClock(169)
        with self.assertRaises(ValueError): ManualClock(1.2)
        self.clock.advance_to(5)
        with self.assertRaises(ValueError): self.clock.advance_to(4)

    def test_fees_and_diamond(self):
        for p in range(12):
            self.assertEqual(Doctor(id=1, name="D", p=p).fee(), 40 + 5*(p % 5))
            self.assertEqual(Nurse(id=2, name="N", p=p).fee(), 10 + p % 3)
            self.assertEqual(Pharmacist(id=3, name="P", p=p).fee(), 5)
        before = Person.construction_count()
        m = MedicalLecturer(id=4, name="M", p=7, module="Anatomy")
        self.assertEqual(Person.construction_count() - before, 1)
        self.assertEqual((m.role(), m.fee(), m.module), ("Doctor and Lecturer", 50, "Anatomy"))

    def test_cancel_boundaries_and_terminal_state(self):
        c = self.clinic(3)
        c.book(20, 10, 1, 10); c.confirm(20)
        self.clock.advance_to(8); c.cancel(20)
        with self.assertRaises(ValueError): c.confirm(20)
        with self.assertRaises(ValueError): c.cancel(20)
        c.book(21, 10, 1, 12); c.confirm(21)
        self.clock.advance_to(11)
        with self.assertRaisesRegex(ValueError, "too late"): c.cancel(21)
        c.book(22, 11, 2, 12)
        c.cancel(22)
        c.book(23, 11, 2, 12)
        self.clock.advance_to(12)
        for id in (21, 23):
            with self.assertRaisesRegex(ValueError, "started"): c.cancel(id)
        self.assertIn("FAILED cancel #21: too late", self.path.read_text())

    def test_conflicts_ids_and_immutable_queries(self):
        c = self.clinic(3); c.book(20, 10, 1, 10)
        before = c.appointments()
        for args in [(21,11,1,10), (22,10,2,10), (1,11,2,11), (20,11,2,11), (23,99,2,11)]:
            with self.assertRaises((ValueError, KeyError)): c.book(*args)
        with self.assertRaises(ValueError): c.add_patient(Patient(id=20,name="X"))
        self.assertEqual(before,c.appointments())
        with self.assertRaises(TypeError): before[0][4] = "CANCELLED"
        c.cancel(20); c.book(21, 10, 1, 10)
        self.assertEqual(before[0][4], "PENDING")

    def test_week_boundaries(self):
        c = self.clinic(3)
        c.book(20,10,1,0); c.book(21,10,1,167)
        for hour in (-1, 168, 2.5, True):
            with self.assertRaises(ValueError): c.book(30,11,2,hour)
        self.clock.advance_to(5)
        with self.assertRaises(ValueError): c.book(30,11,2,4)

    def test_waiting_skips_conflict_and_preserves_fifo(self):
        c = self.clinic(0)
        c.book(20,10,1,10); c.book(21,11,2,10)
        c.join_waiting_list(11,1); c.join_waiting_list(12,1); c.join_waiting_list(13,1)
        with self.assertRaises(ValueError): c.join_waiting_list(12,1)
        c.cancel(20)
        self.assertEqual(c.waiting_list(1),(11,13))
        offered = c.appointments()[-1]
        self.assertEqual(offered[1:5],(12,1,10,"PENDING"))
        c.cancel(offered[0])
        self.assertEqual(c.appointments()[-1][1],13)
        self.assertEqual(c.waiting_list(1),(11,))

    def test_emergency_is_atomic_for_invalid_request(self):
        c = self.clinic(1); c.book(20,10,1,10)
        with self.assertRaises(ValueError): c.book(21,12,1,10,emergency=True)
        self.assertEqual(c.appointments()[0][4],"PENDING")
        c.book(21,11,1,10,emergency=True)
        self.assertEqual(c.appointments()[0][4:],("CANCELLED","45","bumped"))
        c.confirm(21)
        before=c.appointments()
        with self.assertRaises(ValueError): c.book(22,11,1,10,emergency=True)
        self.assertEqual(before,c.appointments())
        c.book(23,10,1,15); c.confirm(23)
        with self.assertRaises(ValueError): c.book(24,11,1,15,emergency=True)
        c.book(25,10,2,20); self.clock.advance_to(20)
        with self.assertRaises(ValueError): c.book(26,11,2,20,emergency=True)

    def test_buffers_both_directions(self):
        c = self.clinic(2); c.book(20,10,1,10)
        for hour in (8,9,11,12):
            with self.assertRaises(ValueError): c.book(21,11,1,hour)
        c.book(21,11,1,7); c.book(22,11,1,13)
        c.book(23,10,2,20)
        with self.assertRaises(ValueError): c.book(24,11,2,21)
        c.book(24,11,2,22)
        c.book(25,10,3,30); c.book(26,11,3,31)

    def test_discounts(self):
        c = self.clinic(3)
        for id,patient in enumerate((11,12,13),20): c.book(id,patient,1,id)
        self.assertEqual([a[5] for a in c.appointments()],["27.5","0","55"])

    def test_open_closed_once_on_exception(self):
        out=io.StringIO()
        with redirect_stdout(out):
            with self.assertRaisesRegex(ValueError,"deliberate"):
                with AppointmentLog(Path(self.temp.name)/"other.log") as log:
                    log.write("before error")
                    raise ValueError("deliberate")
        self.assertEqual(out.getvalue(),"[log] opened\n[log] closed\n")

    def test_log_io_failures(self):
        stream=io.StringIO()
        with patch("builtins.open",return_value=stream) as opened:
            log=AppointmentLog("unused")
            with log:
                with patch.object(stream,"write",side_effect=OSError("disk full")):
                    with self.assertRaises(OSError): log.write("test")
                with self.assertRaises(RuntimeError): log.write("test")
            self.assertTrue(stream.closed)
            opened.assert_called_once()
        stream=io.StringIO()
        with patch("builtins.open",return_value=stream):
            with patch.object(stream,"close",side_effect=OSError("close failed")) as close:
                with self.assertRaisesRegex(ValueError,"original") as caught:
                    with AppointmentLog("unused"):
                        raise ValueError("original")
                close.assert_called_once()
                self.assertIn("close failed",caught.exception.__notes__[0])
        stream.close()

    def test_new_staff_subclass_requires_no_clinic_change(self):
        class Physiotherapist(Staff):
            def role(self): return "Physiotherapist"
            def fee(self): return 25
            def buffer_hours(self): return 3
        c=self.clinic(2)
        c.add_staff(Physiotherapist(id=4,name="New",p=2))
        c.book(20,10,4,10)
        with self.assertRaises(ValueError): c.book(21,11,4,13)
        c.book(21,11,4,14)


if __name__ == "__main__":
    unittest.main()
