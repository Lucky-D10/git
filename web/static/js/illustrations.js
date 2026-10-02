// Original vector illustrations used throughout the local interface.
export function portrait(lane=0,wear=false){
 const blue=lane===0,color=blue?'#268cf0':'#ff9b29',dark=blue?'#165eb8':'#d37813';
 return `<svg class="${wear?'headband-art':'portrait-art'} ${blue?'blue':'orange'}" viewBox="0 0 180 170" aria-hidden="true">
 <circle cx="90" cy="86" r="75" fill="${blue?'#dcf0ff':'#ffeed7'}"/>
 ${!blue?'<path d="M121 39Q152 32 150 65L159 113Q151 136 131 128L124 85Z" fill="#49352c"/><path d="M144 54q18 34 6 61" fill="none" stroke="#674638" stroke-width="8"/>':''}
 <path d="M35 167q-4-38 33-47h44q37 9 33 47Z" fill="${color}"/>
 <path d="m67 124 23 16 23-16-8 34H76Z" fill="${dark}"/><path d="m70 126 20 16 20-16" fill="none" stroke="#acd8f9" stroke-width="3"/>
 <path d="M77 111h26v21q-13 11-26 0Z" fill="#ffcba5"/>
 <ellipse cx="48" cy="82" rx="9" ry="13" fill="#ffd0ae"/><ellipse cx="132" cy="82" rx="9" ry="13" fill="#ffd0ae"/>
 <path d="M47 66q0-43 43-43t43 43v21q-2 36-43 40-41-4-43-40Z" fill="#ffddbd"/>
 <path d="M45 76Q31 37 63 29L63 21l14 5 12-12 8 10q40-8 44 34l-10 23-6-28q-17 5-28-8-15 19-41 17l-3 19Z" fill="${blue?'#263d63':'#49352c'}"/>
 <path d="M50 52q10-23 34-20M98 30q22-3 31 17" fill="none" stroke="${blue?'#34517c':'#604235'}" stroke-width="5" stroke-linecap="round"/>
 <ellipse cx="73" cy="82" rx="7" ry="9" fill="#fff"/><ellipse cx="107" cy="82" rx="7" ry="9" fill="#fff"/>
 <ellipse cx="74" cy="83" rx="4.5" ry="7" fill="#253344"/><ellipse cx="106" cy="83" rx="4.5" ry="7" fill="#253344"/>
 <circle cx="76" cy="80" r="2" fill="#fff"/><circle cx="108" cy="80" r="2" fill="#fff"/>
 <path d="m68 69 10-1m24 0 10 1" stroke="#5b4338" stroke-width="3" stroke-linecap="round"/>
 <path d="m89 87-2 8 5 1" fill="none" stroke="#eeb18e" stroke-width="2" stroke-linecap="round"/>
 <ellipse cx="62" cy="99" rx="9" ry="5" fill="#f5b396" opacity=".6"/><ellipse cx="118" cy="99" rx="9" ry="5" fill="#f5b396" opacity=".6"/>
 <path d="M79 105q11 11 22 0" fill="none" stroke="#b9604e" stroke-width="2.8" stroke-linecap="round"/>
 ${wear?'<path d="M44 55q45-19 91 0l-2 20q-44-14-86 0Z" fill="#193a59" stroke="#315c7e" stroke-width="2"/><path d="m59 61 13-3m38 0 13 3" stroke="#39b9ff" stroke-width="4" stroke-linecap="round"/><path d="m82 64 4-8 4 11 4-11 4 8" fill="none" stroke="#c0ebff" stroke-width="2" stroke-linecap="round"/><path d="m36 86 9-21 8 1-5 21-4 5-9 37-14-9Z" fill="#ffcfac"/><path d="m145 87-9-21-8 1 5 21 4 5 9 35 14-9Z" fill="#ffcfac"/><path d="m23 113 23 10-8 36-17-6q-8-19 2-40Zm112 10 24-10q10 25-1 40l-17 6Z" fill="'+color+'" stroke="'+dark+'" stroke-width="2"/>':''}
 <path d="M85 142v17m11-17v17" stroke="#d9eeff" stroke-width="2" stroke-linecap="round"/>
 </svg>`;
}
export function calmArt(){return `<svg class="calm-art" viewBox="0 0 400 100" preserveAspectRatio="none" aria-hidden="true"><circle cx="350" cy="24" r="16" fill="#ffe7a5"/><path d="M0 85Q40 55 85 90T200 87L270 64l33 13 36-30 61 30v23H0Z" fill="#d1f2f9"/><path d="m220 100 79-31 22 9 24-14 55 29v7ZM0 83q44-4 70 17H0Z" fill="#bfeaf3"/></svg>`;}
