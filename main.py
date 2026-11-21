"""Run with python main.py, or python main.py --p 7."""
import argparse
from clinic import (AppointmentLog, Clinic, ManualClock, Person, Patient,
                    StudentPatient, StaffMemberPatient, VisitorPatient,
                    Doctor, Nurse, Pharmacist, MedicalLecturer)


def expected_failure(label, action):
    try:
        action()
    except (ValueError, KeyError) as error:
        print(f"Expected failure ({label}): {error}")
    else:
        raise AssertionError(f"Expected failure did not happen: {label}")


def demo(p, path):
    print(f"P={p}; assigned twist={p % 4}")
    clock = ManualClock()
    with AppointmentLog(path) as log:
        clinic = Clinic(p, clock, log)
        team = [Doctor(id=1, name="Dr Moyo", p=p),
                Nurse(id=2, name="Nurse Dube", p=p),
                Pharmacist(id=3, name="Mr Ncube", p=p)]
        before = Person.construction_count()
        teacher = MedicalLecturer(id=4, name="Dr Zhou", p=p, module="Anatomy")
        print("MedicalLecturer Person constructor calls:", Person.construction_count() - before)
        print("Module:", teacher.module)
        team.append(teacher)
        print("\nPolymorphic staff loop:")
        for staff in team:
            print(f"{staff.role()}: {staff.fee()}")
            clinic.add_staff(staff)
        patients = [Patient(id=10, name="Tariro"),
                    StudentPatient(id=11, name="Tendai", emergency=True),
                    StaffMemberPatient(id=12, name="Rudo"),
                    VisitorPatient(id=13, name="Farai")]
        for patient in patients:
            clinic.add_patient(patient)
        expected_failure("empty name", lambda: Patient(id=20, name=" "))
        expected_failure("nonpositive id", lambda: Patient(id=0, name="Test"))
        expected_failure("duplicate id", lambda: clinic.add_patient(Patient(id=1, name="Duplicate")))
        clinic.book(100, 10, 1, 10)
        clinic.confirm(100)
        expected_failure("staff conflict", lambda: clinic.book(101, 11, 1, 10))
        expected_failure("patient conflict", lambda: clinic.book(102, 10, 2, 10))
        clinic.book(103, 11, 2, 12)
        clinic.confirm(103)
        clock.advance_to(8)
        clinic.cancel(100)
        expected_failure("terminal cancellation", lambda: clinic.confirm(100))
        clock.advance_to(11)
        expected_failure("less than two hours", lambda: clinic.cancel(103))
        clock.advance_to(12)
        expected_failure("already started", lambda: clinic.cancel(103))
        print("\nAssigned twist demonstration:")
        if p % 4 == 0:
            clinic.book(200, 10, 1, 30)
            clinic.book(201, 11, 2, 30)
            clinic.join_waiting_list(11, 1)
            clinic.join_waiting_list(12, 1)
            clinic.cancel(200)
            print("Waiting queue after offer:", clinic.waiting_list(1))
        elif p % 4 == 1:
            clinic.book(200, 10, 1, 30)
            clinic.book(201, 11, 1, 30, emergency=True)
            clinic.confirm(201)
            clinic.book(202, 10, 1, 40)
            clinic.confirm(202)
            expected_failure("confirmed cannot be bumped",
                             lambda: clinic.book(203, 11, 1, 40, emergency=True))
        elif p % 4 == 2:
            clinic.book(200, 10, 1, 30)
            expected_failure("doctor buffer", lambda: clinic.book(201, 11, 1, 32))
            clinic.book(202, 11, 1, 33)
            clinic.book(203, 10, 2, 40)
            expected_failure("nurse buffer", lambda: clinic.book(204, 11, 2, 41))
            clinic.book(205, 11, 2, 42)
            clinic.book(206, 10, 3, 50)
            clinic.book(207, 11, 3, 51)
        else:
            for id, patient in enumerate(patients[1:], start=200):
                clinic.book(id, patient.id, 1, 30 + id - 200)
        print("\nImmutable appointment snapshots:")
        print("(id, patient_id, staff_id, start, status, price, reason)")
        for row in clinic.appointments():
            print(row)
    print(f"\nRead {path} for ATTEMPT, OK, FAILED and twist events.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p", type=int)
    parser.add_argument("--log", default="appointments.log")
    args = parser.parse_args()
    p = args.p
    while p is None or p < 0:
        try:
            p = int(input("Enter your assigned P (non-negative integer): "))
        except ValueError:
            p = None
    demo(p, args.log)


if __name__ == "__main__":
    main()
