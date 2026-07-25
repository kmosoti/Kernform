export def "kf test" [tier: string = "fast", ...rest: string] { ^kernform test $tier ...$rest }
