const users = new Map([[1, "Ada"], [2, "Linus"]]);

function getUserById(id) {
  return users.get(id) ?? null;
}

module.exports = { getUserById };
