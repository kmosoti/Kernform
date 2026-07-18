export def "kf check" [...rest: string] { ^kernform check ...$rest }
export def "kf init" [name: string, ...rest: string] { ^kernform init $name ...$rest }
