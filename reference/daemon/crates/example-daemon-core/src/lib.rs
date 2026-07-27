//! Pure native domain operations.

/// Add two values without performing effects.
#[must_use]
pub const fn add(left: i64, right: i64) -> i64 {
    left + right
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds_values() {
        assert_eq!(add(20, 22), 42);
    }
}
