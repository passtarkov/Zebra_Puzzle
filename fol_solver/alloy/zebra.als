-- ============================================================
-- Section 1: Signatures
-- ============================================================

abstract sig Agent {}
one sig Russian, English, Chinese, German, French, American extends Agent {}

abstract sig House {}
one sig House1, House2, House3, House4, House5, House6 extends House {}

abstract sig Pet {}
one sig Dog, Cat, Zebra, Fish, Hamster, Bear extends Pet {}

-- ============================================================
-- Section 2: World state signature
-- ============================================================

one sig World {
  owns_house : Agent -> House,
  owns_pet   : Agent -> Pet,
  at         : Agent -> House
}

-- ============================================================
-- Section 3: Facts (invariants from report Section 5.2)
-- ============================================================

-- Every agent owns exactly one house
fact OneHousePerAgent {
  all a: Agent | one a.(World.owns_house)
}

-- Every house is owned by exactly one agent
fact OneAgentPerHouse {
  all h: House | one (World.owns_house).h
}

-- Every agent owns exactly one pet
fact OnePetPerAgent {
  all a: Agent | one a.(World.owns_pet)
}

-- Every pet is owned by exactly one agent
fact OneAgentPerPet {
  all p: Pet | one (World.owns_pet).p
}

-- Every agent is in exactly one house at the current snapshot
fact AtMostOneLocation {
  all a: Agent | one a.(World.at)
}

-- ============================================================
-- Section 4: Predicates for verification
-- ============================================================

pred validWorld {
  -- All invariants hold implicitly from the facts above;
  -- exposed here as a named predicate for explicit run commands
}

pred someAgentVisiting {
  -- At least one agent is in a house they do not own
  some a: Agent | a.(World.at) != a.(World.owns_house)
}

-- ============================================================
-- Section 5: Run and check commands
-- ============================================================

run validWorld for 6

run someAgentVisiting for 6

check NoOrphanHouses {
  -- No house exists without an owner; follows from OneAgentPerHouse
  all h: House | some a: Agent | h = a.(World.owns_house)
} for 6

check NoSharedPet {
  -- No two distinct agents own the same pet; follows from OneAgentPerPet
  no disj a1, a2: Agent | a1.(World.owns_pet) = a2.(World.owns_pet)
} for 6
