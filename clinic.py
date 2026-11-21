"""Clinic mini project: standard-library-only, simulated whole-hour time."""
from abc import ABC, abstractmethod
from decimal import Decimal
from operator import index


def integer(value, label, minimum=0, maximum=None):
    # Integer protocol validation, without class/type inspection.
    try:
        if value is True or value is False:
            raise TypeError
        value = index(value)
    except TypeError:
        raise ValueError(f"{label} must be a whole number") from None
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label} must be an integer from {minimum}" +
                         (f" to {maximum}" if maximum is not None else " upwards"))
    return value


def nonempty(value, label):
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must not be empty")
    return value


class Clock(ABC):
    @abstractmethod
    def now(self):
        pass


class ManualClock(Clock):
    def __init__(self, hour=0):
        self.__hour = integer(hour, "hour", 0, 168)

    def now(self):
        return self.__hour

    def advance_to(self, hour):
        self.__hour = integer(hour, "hour", self.__hour, 168)


class Person(ABC):
    __construction_count = 0

    def __init__(self, *, name, id, **kwargs):
        super().__init__(**kwargs)
        self.__name = nonempty(name, "name")
        self.__id = integer(id, "id", 1)
        Person.__construction_count += 1

    @classmethod
    def construction_count(cls):
        return Person.__construction_count

    @property
    def name(self):
        return self.__name

    @property
    def id(self):
        return self.__id

    @abstractmethod
    def role(self):
        pass


class Patient(Person):
    def __init__(self, *, emergency=False, **kwargs):
        self.__emergency = bool(emergency)
        super().__init__(**kwargs)

    @property
    def emergency(self):
        return self.__emergency

    def role(self):
        return "Patient"

    def price(self, fee):
        return Decimal(fee)


class StudentPatient(Patient):
    def price(self, fee):
        return Decimal(fee) / 2


class StaffMemberPatient(Patient):
    def price(self, fee):
        return Decimal(0)


class VisitorPatient(Patient):
    pass


class Staff(Person):
    def __init__(self, *, p, **kwargs):
        self.__p = integer(p, "P")
        super().__init__(**kwargs)

    @property
    def p(self):
        return self.__p

    @abstractmethod
    def fee(self):
        pass

    def buffer_hours(self):
        return 0


class Doctor(Staff):
    def role(self):
        return "Doctor"

    def fee(self):
        return 40 + 5 * (self.p % 5)

    def buffer_hours(self):
        return 2


class Nurse(Staff):
    def role(self):
        return "Nurse"

    def fee(self):
        return 10 + self.p % 3

    def buffer_hours(self):
        return 1


class Pharmacist(Staff):
    def role(self):
        return "Pharmacist"

    def fee(self):
        return 5


class Lecturer(Person):
    def __init__(self, *, module, **kwargs):
        self.__module = nonempty(module, "module")
        super().__init__(**kwargs)

    @property
    def module(self):
        return self.__module

    def role(self):
        return "Lecturer"


class MedicalLecturer(Doctor, Lecturer):
    def role(self):
        return "Doctor and Lecturer"


class Status:
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# Invariants: positive id; start is a whole hour in [0, 167], duration 1;
# patient/staff/start/price are fixed; status follows PENDING -> CONFIRMED,
# PENDING -> CANCELLED or CONFIRMED -> CANCELLED; cancellation is terminal.
# Cancellation is forbidden at/after start, and confirmed cancellation requires
# at least two hours remaining. Only Clinic holds live Appointment references.
class Appointment:
    def __init__(self, id, patient, staff, start, price):
        self.__id = integer(id, "appointment id", 1)
        self.__patient = patient
        self.__staff = staff
        self.__start = integer(start, "start", 0, 167)
        self.__price = Decimal(price)
        self.__status = Status.PENDING
        self.__reason = ""

    @property
    def id(self): return self.__id

    @property
    def patient(self): return self.__patient

    @property
    def staff(self): return self.__staff

    @property
    def start(self): return self.__start

    @property
    def status(self): return self.__status

    def confirm(self):
        if self.__status != Status.PENDING:
            raise ValueError("only a pending appointment can be confirmed")
        self.__status = Status.CONFIRMED

    def check_cancel(self, now):
        if self.__status == Status.CANCELLED:
            raise ValueError("appointment is already cancelled")
        if now >= self.__start:
            raise ValueError("appointment has started")
        if self.__status == Status.CONFIRMED and self.__start - now < 2:
            raise ValueError("too late")

    def cancel(self, now, reason="cancelled"):
        self.check_cancel(now)
        self.__reason = nonempty(reason, "reason")
        self.__status = Status.CANCELLED

    def snapshot(self):
        return (self.id, self.patient.id, self.staff.id, self.start,
                self.status, str(self.__price), self.__reason)


class AppointmentLog:
    """One context owns one open and one close; unusable after I/O failure."""
    def __init__(self, path):
        self.__path = path
        self.__stream = None
        self.__used = False
        self.__broken = False

    def __enter__(self):
        if self.__used:
            raise RuntimeError("log context cannot be reused")
        self.__used = True
        self.__stream = open(self.__path, "a", encoding="utf-8")
        print("[log] opened")
        return self

    def write(self, message):
        if self.__stream is None or self.__stream.closed or self.__broken:
            raise RuntimeError("log is unavailable")
        try:
            self.__stream.write(message + "\n")
            self.__stream.flush()
        except OSError:
            self.__broken = True
            raise

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.__stream.close()
        except OSError as close_error:
            if exc is None:
                raise
            exc.add_note(f"Additionally, log close failed: {close_error}")
        else:
            print("[log] closed")
        return False


# Invariants: one global id namespace for registered people and appointments;
# appointments refer to registered patient/staff objects; active appointments
# never share a patient/hour or staff/hour; cancelled slots do not conflict.
# For twist 2, staff appointments have >= buffer_hours() empty hours between.
# Collections are private; queries return immutable tuples of scalar snapshots.
# All commands log ATTEMPT and OK/FAILED; validation precedes mutation.
class Clinic:
    def __init__(self, p, clock, log):
        self.__p = integer(p, "P")
        self.__clock = clock
        self.__log = log
        self.__patients = {}
        self.__staff = {}
        self.__appointments = {}
        self.__waiting = {}
        self.__used_ids = set()

    def __action(self, label):
        from contextlib import contextmanager

        @contextmanager
        def action():
            self.__log.write(f"ATTEMPT {label}")
            try:
                yield
            except Exception as error:
                try:
                    self.__log.write(f"FAILED {label}: {error}")
                except Exception as log_error:
                    error.add_note(f"Additionally, failure logging failed: {log_error}")
                raise
            else:
                self.__log.write(f"OK {label}")
        return action()

    def __unused(self, id):
        integer(id, "id", 1)
        if id in self.__used_ids:
            raise ValueError("id is already used in this Clinic")

    def add_patient(self, patient):
        with self.__action(f"register patient #{patient.id}"):
            self.__unused(patient.id)
            self.__patients[patient.id] = patient
            self.__used_ids.add(patient.id)

    def add_staff(self, staff):
        with self.__action(f"register staff #{staff.id}"):
            self.__unused(staff.id)
            if staff.p != self.__p:
                raise ValueError("staff P must match clinic P")
            self.__staff[staff.id] = staff
            self.__used_ids.add(staff.id)

    def __conflicts(self, patient, staff, start):
        gap = staff.buffer_hours() if self.__p % 4 == 2 else 0
        return [a for a in self.__appointments.values()
                if a.status != Status.CANCELLED and
                ((a.patient.id == patient.id and a.start == start) or
                 (a.staff.id == staff.id and abs(a.start - start) < 1 + gap))]

    def book(self, id, patient_id, staff_id, start, *, emergency=False):
        with self.__action(f"book #{id}"):
            self.__unused(id)
            integer(start, "start", 0, 167)
            if start < self.__clock.now():
                raise ValueError("cannot book in the past")
            patient = self.__patients[patient_id]
            staff = self.__staff[staff_id]
            conflicts = self.__conflicts(patient, staff, start)
            if emergency and (self.__p % 4 != 1 or not patient.emergency):
                raise ValueError("emergency booking requires twist 1 and a flagged patient")
            if conflicts:
                if not emergency:
                    raise ValueError("patient or staff scheduling conflict")
                if any(a.patient.id == patient_id or a.status != Status.PENDING
                       for a in conflicts):
                    raise ValueError("cannot bump this appointment (confirmed or patient conflict)")
                for a in conflicts:
                    a.check_cancel(self.__clock.now())
            price = patient.price(staff.fee()) if self.__p % 4 == 3 else Decimal(staff.fee())
            new = Appointment(id, patient, staff, start, price)
            for a in conflicts:
                self.__log.write(f"BUMP #{a.id}: reason=bumped; replacement=#{id}")
            for a in conflicts:
                a.cancel(self.__clock.now(), "bumped")
            self.__appointments[id] = new
            self.__used_ids.add(id)
            return id

    def confirm(self, id):
        with self.__action(f"confirm #{id}"):
            self.__appointments[id].confirm()

    def cancel(self, id, reason="cancelled"):
        with self.__action(f"cancel #{id}"):
            appointment = self.__appointments[id]
            appointment.cancel(self.__clock.now(), reason)
            if self.__p % 4 == 0:
                self.__offer(appointment.staff, appointment.start)

    def join_waiting_list(self, patient_id, staff_id):
        with self.__action(f"wait patient #{patient_id} staff #{staff_id}"):
            if self.__p % 4 != 0:
                raise ValueError("waiting lists require twist 0")
            self.__patients[patient_id]
            self.__staff[staff_id]
            queue = self.__waiting.setdefault(staff_id, [])
            if patient_id in queue:
                raise ValueError("patient already waiting")
            queue.append(patient_id)

    def __offer(self, staff, start):
        queue = self.__waiting.get(staff.id, [])
        for patient_id in tuple(queue):
            patient = self.__patients[patient_id]
            if not self.__conflicts(patient, staff, start):
                id = max(self.__used_ids, default=0) + 1
                self.__log.write(f"OFFER slot {start} to patient #{patient_id} as #{id}")
                self.book(id, patient_id, staff.id, start)
                queue.remove(patient_id)
                break

    def appointments(self):
        return tuple(a.snapshot() for a in self.__appointments.values())

    def waiting_list(self, staff_id):
        return tuple(self.__waiting.get(staff_id, ()))


__all__ = [
    "Appointment", "AppointmentLog", "Clinic", "Clock", "Doctor",
    "Lecturer", "ManualClock", "MedicalLecturer", "Nurse", "Patient",
    "Person", "Pharmacist", "Staff", "StaffMemberPatient",
    "StudentPatient", "VisitorPatient", "integer", "nonempty",
]

Status.PENDING = Status.PENDING if hasattr(Status, "PENDING") else "PENDING"
Status.CONFIRMED = Status.CONFIRMED if hasattr(Status, "CONFIRMED") else "CONFIRMED"
Status.CANCELLED = Status.CANCELLED if hasattr(Status, "CANCELLED") else "CANCELLED"

__all__ += ["Status"]
