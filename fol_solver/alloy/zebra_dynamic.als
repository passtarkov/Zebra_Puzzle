module fol_solver/alloy/zebra_dynamic
open util/ordering[Time]

-- ============================================================
-- Section 2: Time signature
-- ============================================================

sig Time {}

-- ============================================================
-- Section 3: Domain signatures
-- ============================================================

abstract sig Agent {}
one sig Russian, English, Chinese, German, French, American extends Agent {}

abstract sig House {}
one sig House1, House2, House3, House4, House5, House6 extends House {}

abstract sig Pet {}
one sig Dog, Cat, Zebra, Fish, Hamster, Bear extends Pet {}

-- ============================================================
-- Section 4: World state (time-indexed)
-- ============================================================

one sig State {
  owns_house : Agent -> House -> Time,
  owns_pet   : Agent -> Pet   -> Time,
  at         : Agent -> House -> Time
}

-- ============================================================
-- Section 5: Static invariants — must hold at every time
-- ============================================================

-- a.(State.owns_house).t  =  (join Agent a with ternary) then join Time t  -> House
fact OneHousePerAgent {
  all t: Time, a: Agent | one a.(State.owns_house).t
}

-- State.owns_house.t.h  =  time-slice -> Agent->House, then join House h  -> Agent
fact OneAgentPerHouse {
  all t: Time, h: House | one State.owns_house.t.h
}

fact OnePetPerAgent {
  all t: Time, a: Agent | one a.(State.owns_pet).t
}

fact OneAgentPerPet {
  all t: Time, p: Pet | one State.owns_pet.t.p
}

fact AtMostOneLocation {
  all t: Time, a: Agent | one a.(State.at).t
}

-- ============================================================
-- Section 6: Event signatures
-- ============================================================

abstract sig Event {
  pre  : one Time,
  post : one Time
} {
  post = pre.next   -- events consume exactly one timestep; pre cannot be last
}

sig StartTrip extends Event {
  agent  : one Agent,
  h_from : one House,
  h_to   : one House
}

-- split into subtypes to avoid needing a Bool sig
abstract sig FinishTrip extends Event {
  agent : one Agent,
  house : one House
}
sig SuccessFinish, FailFinish extends FinishTrip {}

sig ChangeHouse extends Event {
  a1     : one Agent,
  a2     : one Agent,
  h1_new : one House,
  h2_new : one House
}

sig ChangePet extends Event {
  a1     : one Agent,
  a2     : one Agent,
  p1_new : one Pet,
  p2_new : one Pet
}

-- ============================================================
-- Section 7: Event semantics
-- ============================================================

fact StartTripSemantics {
  all e: StartTrip |
    -- tripping agent departs h_from (now in transit at some other house)
    e.agent.(State.at).(e.post) != e.h_from
    -- other agents' locations are frozen
    and (all a: Agent - e.agent |
          a.(State.at).(e.post) = a.(State.at).(e.pre))
    -- ownership is unchanged across a departure
    and State.owns_house.(e.post) = State.owns_house.(e.pre)
    and State.owns_pet.(e.post)   = State.owns_pet.(e.pre)
}

fact FinishTripSemantics {
  all e: SuccessFinish |
    -- successful arrival: agent is now at the destination house
    e.agent.(State.at).(e.post) = e.house
    and (all a: Agent - e.agent |
          a.(State.at).(e.post) = a.(State.at).(e.pre))
    and State.owns_house.(e.post) = State.owns_house.(e.pre)
    and State.owns_pet.(e.post)   = State.owns_pet.(e.pre)
  all e: FailFinish |
    -- failed arrival: nothing changes
    State.at.(e.post)         = State.at.(e.pre)
    and State.owns_house.(e.post) = State.owns_house.(e.pre)
    and State.owns_pet.(e.post)   = State.owns_pet.(e.pre)
}

fact ChangeHouseSemantics {
  all e: ChangeHouse |
    -- the two parties receive their new houses at post
    e.a1.(State.owns_house).(e.post) = e.h1_new
    and e.a2.(State.owns_house).(e.post) = e.h2_new
    -- all other agents' house ownership is frozen
    and (all a: Agent - (e.a1 + e.a2) |
          a.(State.owns_house).(e.post) = a.(State.owns_house).(e.pre))
    -- pets and locations are unchanged
    and State.owns_pet.(e.post) = State.owns_pet.(e.pre)
    and State.at.(e.post)       = State.at.(e.pre)
}

fact ChangePetSemantics {
  all e: ChangePet |
    -- the two parties receive their new pets at post
    e.a1.(State.owns_pet).(e.post) = e.p1_new
    and e.a2.(State.owns_pet).(e.post) = e.p2_new
    -- all other agents' pet ownership is frozen
    and (all a: Agent - (e.a1 + e.a2) |
          a.(State.owns_pet).(e.post) = a.(State.owns_pet).(e.pre))
    -- houses and locations are unchanged
    and State.owns_house.(e.post) = State.owns_house.(e.pre)
    and State.at.(e.post)         = State.at.(e.pre)
}

-- ============================================================
-- Section 8: Frame axiom
-- ============================================================

-- If no event fires at time t, the entire state is frozen
fact FrameAxiom {
  all t: Time - last |
    (no e: Event | e.pre = t) implies (
      State.owns_house.(t.next) = State.owns_house.t
      and State.owns_pet.(t.next)   = State.owns_pet.t
      and State.at.(t.next)         = State.at.t
    )
}

fact AtMostOneEventPerTime {
  all t: Time | lone e: Event | e.pre = t
}

-- ============================================================
-- Section 9: Initial state predicate
-- ============================================================

pred init {
  -- at time 0 every agent is located in the house they own
  all a: Agent | a.(State.at).first = a.(State.owns_house).first
}

fact { init }

-- ============================================================
-- Section 10: Verification commands
-- ============================================================

-- sanity: model is consistent — there exists a valid 5-step trace with at least one event
run someTrace { some Event } for 6 but 5 Time

-- each bijection invariant from Section 5.2 must hold across all time
check HouseBijectionPreserved {
  all t: Time | all a: Agent | one a.(State.owns_house).t
} for 6 but 5 Time

check PetBijectionPreserved {
  all t: Time | all a: Agent | one a.(State.owns_pet).t
} for 6 but 5 Time

check LocationUniqueness {
  all t: Time | all a: Agent | one a.(State.at).t
} for 6 but 5 Time

check NoSharedHouseAcrossTime {
  all t: Time | no disj a1, a2: Agent |
    a1.(State.owns_house).t = a2.(State.owns_house).t
} for 6 but 5 Time

check NoSharedPetAcrossTime {
  all t: Time | no disj a1, a2: Agent |
    a1.(State.owns_pet).t = a2.(State.owns_pet).t
} for 6 but 5 Time
